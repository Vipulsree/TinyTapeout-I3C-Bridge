/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Minimal MIPI I3C Basic SDR target (docs/architecture.md, "Target FSM").
// Works on the synchronised SCL / SDA and the bus conditions from i3c_bus_cond.
//
// Supported: 7'h7E broadcast (always ACKed), private write / read to the
// dynamic address, ENTDAA with arbitration, RSTDAA, ENTHDR0-7 (ignore until the
// HDR Exit Pattern), parity errors TE1-TE3. Other CCCs: broadcast ones are
// ignored, direct ones (SETDASA included) get the dynamic address NACKed.
// SETDASA and TE0 detection were removed to fit the tile (docs/architecture.md).
//
// SDA driver: open-drain phases (ACK, ENTDAA identity) only ever pull low;
// push-pull phases (read data and T-bits) drive both levels. The drive changes
// only after SCL falls, except the End-of-Data hand-off: the target lets go of
// SDA when SCL rises in a read T-bit. Driver outputs are registers.
module i3c_tgt (
    input wire clk,
    input wire rst_n,

    // Bus (synchronised) and bus conditions
    input wire scl,
    input wire sda,
    input wire scl_rise,
    input wire scl_fall,
    input wire start,     // START or repeated START
    input wire stop,
    input wire hdr_exit,
    input wire timeout,   // bus stalled mid-transfer: release SDA, back to IDLE

    output reg sda_oe,
    output reg sda_out,

    // i3c_daa
    output wire [5:0] id_idx,
    input  wire       id_bit,
    input  wire [6:0] da,
    input  wire       da_valid,
    output wire       set_da,
    output wire [6:0] new_da,
    output wire       clr_da,

    // cmd_ctrl
    output wire [7:0] rx_data,
    output wire       rx_valid,
    output wire       frame_start,
    output wire       frame_rd,
    output wire       frame_end,
    input  wire [7:0] tx_data,
    input  wire       tx_last,
    output wire       tx_take,
    input  wire       can_read,
    input  wire       can_write,
    output wire       par_err,

    output wire       active,  // inside a transfer (for the stall timeout)
    output wire [3:0] state
);

  localparam [3:0] S_IDLE = 4'd0,     // wait for START
                   S_ADDR = 4'd1,     // 7-bit address + R/W
                   S_ACK = 4'd2,      // driving ACK (open-drain low)
                   S_CCC = 4'd3,      // CCC code + T
                   S_DAA_ID = 4'd4,   // ENTDAA: PID, BCR, DCR out, open-drain, arbitration
                   S_DAA_ADDR = 4'd5, // ENTDAA: DA + parity in
                   S_PRIV_WR = 4'd6,  // private write bytes + T
                   S_PRIV_RD = 4'd7,  // private read bytes + End-of-Data T
                   S_HDR = 4'd8,      // ignore everything until the HDR Exit Pattern
                   S_WAIT = 4'd9;     // not addressed, error or lost arbitration: wait for Sr / P

  localparam [2:0] A_WAIT = 3'd0, A_CCC = 3'd1, A_DAA = 3'd2, A_PWR = 3'd3, A_PRD = 3'd4;
  localparam [1:0] X_NONE = 2'd0, X_ENTDAA = 2'd1, X_DIRECT = 2'd2;

  localparam [7:0] CCC_RSTDAA = 8'h06, CCC_ENTDAA = 8'h07;
  localparam [6:0] BCAST = 7'h7E;

  reg [3:0] st;
  reg [5:0] cnt;      // bit counter; ENTDAA identity bit index (63..0)
  reg [7:0] sh;
  reg       par;      // XOR of the data bits received so far (odd parity check)
  reg [2:0] ack_to;   // what follows the ACK being driven
  reg [1:0] ctx;      // CCC context since the last 7E/W: ENTDAA or another direct CCC
  reg       ours;     // a private transfer to us is open
  reg       last;     // the byte being sent is the last one (T = 0)

  // ---------------------------------------------------------------- decode
  wire [6:0] addr = sh[7:1];
  wire       rnw = sh[0];
  wire       own_da = da_valid & (addr == da) & (ctx == X_NONE);
  wire       daa_rd = (addr == BCAST) & rnw & (ctx == X_ENTDAA) & ~da_valid;

  wire bus_ev  = (st != S_HDR) & (timeout | stop | start);
  wire hdr_end = (st == S_ADDR || st == S_DAA_ADDR) & scl_fall & (cnt == 6'd8) & ~bus_ev;
  wire rx_st   = (st == S_CCC) | (st == S_PRIV_WR);
  wire t_bit   = rx_st & scl_rise & (cnt == 6'd8) & ~bus_ev;
  wire par_ok  = par ^ sda;  // odd parity over the 8 data bits and T
  wire ack_end = (st == S_ACK) & scl_fall & ~bus_ev;
  wire rd_next = (st == S_PRIV_RD) & scl_fall & (cnt == 6'd9) & ~bus_ev;
  wire priv_ok = own_da & (rnw ? can_read : can_write);

  assign frame_start = hdr_end & (st == S_ADDR) & (addr != BCAST) & priv_ok;
  assign frame_rd    = rnw;
  assign frame_end   = ours & bus_ev;
  assign rx_data     = sh;
  assign rx_valid    = t_bit & (st == S_PRIV_WR) & par_ok;
  assign par_err     = t_bit & ~par_ok;
  assign tx_take     = (ack_end & (ack_to == A_PRD)) | rd_next;
  assign new_da      = sh[7:1];
  assign set_da      = hdr_end & (st == S_DAA_ADDR) & ^sh;
  assign clr_da      = t_bit & (st == S_CCC) & par_ok & (sh == CCC_RSTDAA);
  assign id_idx      = (st == S_DAA_ID) ? cnt - 6'd1 : 6'd63;
  assign active      = (st != S_IDLE) & (st != S_HDR);
  assign state       = st;

  // ---------------------------------------------------------------- shift register
  // Data only, so no reset: the decode reads it only after 8 bits were shifted
  // in, and the read path only after a byte was loaded.
  always @(posedge clk) begin
    if (st != S_HDR && !bus_ev) begin
      case (st)
        S_ADDR, S_DAA_ADDR, S_CCC, S_PRIV_WR: if (scl_rise && cnt != 6'd8) sh <= {sh[6:0], sda};
        S_ACK: if (ack_end && ack_to == A_PRD) sh <= tx_data;  // first byte of a private read
        S_PRIV_RD:
        if (scl_fall) begin
          if (cnt == 6'd9) sh <= tx_data;  // next byte
          else if (cnt != 6'd8) sh <= {sh[6:0], 1'b0};
        end
        default: ;
      endcase
    end
  end

  // ---------------------------------------------------------------- FSM
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st      <= S_IDLE;
      cnt     <= 6'd0;
      par     <= 1'b0;
      ack_to  <= A_WAIT;
      ctx     <= X_NONE;
      ours    <= 1'b0;
      last    <= 1'b0;
      sda_oe  <= 1'b0;
      sda_out <= 1'b0;
    end else if (st == S_HDR) begin
      if (hdr_exit) st <= S_IDLE;  // the controller follows the pattern with STOP
    end else if (timeout || stop) begin
      st      <= S_IDLE;
      ctx     <= X_NONE;
      ours    <= 1'b0;
      sda_oe  <= 1'b0;
      sda_out <= 1'b0;
    end else if (start) begin
      st      <= S_ADDR;
      cnt     <= 6'd0;
      ours    <= 1'b0;
      sda_oe  <= 1'b0;
      sda_out <= 1'b0;
    end else begin
      case (st)
        // ---------------------------------------------- address header, ENTDAA address
        S_ADDR, S_DAA_ADDR:
        if (scl_rise && cnt != 6'd8) begin
          cnt <= cnt + 6'd1;
        end else if (hdr_end) begin
          st <= S_WAIT;  // NACK unless one of the cases below ACKs
          if (st == S_DAA_ADDR) begin
            if (^sh) begin  // odd parity good: ACK and take the address (else TE3: NACK)
              sda_oe <= 1'b1;
              ack_to <= A_WAIT;
              st     <= S_ACK;
            end
          end else if (addr == BCAST && !rnw) begin
            sda_oe <= 1'b1;
            ack_to <= A_CCC;
            ctx    <= X_NONE;
            st     <= S_ACK;
          end else if (daa_rd) begin
            sda_oe <= 1'b1;
            ack_to <= A_DAA;
            st     <= S_ACK;
          end else if (addr != BCAST && priv_ok) begin
            sda_oe <= 1'b1;
            ack_to <= rnw ? A_PRD : A_PWR;
            ours   <= 1'b1;
            st     <= S_ACK;
          end
        end

        // ---------------------------------------------- end of the ACK bit
        S_ACK:
        if (ack_end) begin
          cnt     <= 6'd0;
          par     <= 1'b0;
          sda_oe  <= 1'b0;
          sda_out <= 1'b0;
          case (ack_to)
            A_CCC:   st <= S_CCC;
            A_PWR:   st <= S_PRIV_WR;
            A_PRD: begin  // first data byte, push-pull
              st      <= S_PRIV_RD;
              last    <= tx_last;
              sda_oe  <= 1'b1;
              sda_out <= tx_data[7];
            end
            A_DAA: begin  // identity MSB, open-drain
              st     <= S_DAA_ID;
              cnt    <= 6'd63;
              sda_oe <= ~id_bit;
            end
            default: st <= S_WAIT;
          endcase
        end

        // ---------------------------------------------- bytes + T-bit in
        S_CCC, S_PRIV_WR:
        if (scl_rise) begin
          if (cnt != 6'd8) begin
            par <= par ^ sda;
            cnt <= cnt + 6'd1;
          end else begin  // T-bit
            cnt <= 6'd0;
            par <= 1'b0;
            if (!par_ok) st <= S_WAIT;  // TE1 (CCC) / TE2 (data): drop, wait for Sr or P
            else if (st == S_CCC) begin
              st <= S_WAIT;
              if (sh == CCC_ENTDAA) ctx <= X_ENTDAA;
              else if (sh[7:3] == 5'b00100) st <= S_HDR;  // ENTHDR0-7
              else if (sh[7]) ctx <= X_DIRECT;             // unsupported direct CCC
            end
          end
        end

        // ---------------------------------------------- private read
        S_PRIV_RD:
        if (scl_rise) begin
          cnt <= cnt + 6'd1;
          if (cnt == 6'd8) begin  // T-bit high phase: hand SDA back to the controller
            sda_oe  <= 1'b0;
            sda_out <= 1'b0;
            if (last) st <= S_WAIT;
          end
        end else if (scl_fall) begin
          if (cnt == 6'd9) begin  // T was 1 and no abort: next byte
            cnt     <= 6'd0;
            last    <= tx_last;
            sda_oe  <= 1'b1;
            sda_out <= tx_data[7];
          end else if (cnt == 6'd8) begin
            sda_out <= ~last;  // T: 1 = more data, 0 = End-of-Data
          end else begin
            sda_out <= sh[6];
          end
        end

        // ---------------------------------------------- ENTDAA identity
        S_DAA_ID:
        if (scl_rise) begin
          if (!sda_oe && !sda) begin  // sent 1 but the bus is 0: lost arbitration
            st <= S_WAIT;
          end
        end else if (scl_fall) begin
          if (cnt == 6'd0) begin  // all 64 bits sent: receive the address
            sda_oe <= 1'b0;
            st     <= S_DAA_ADDR;
          end else begin
            cnt    <= cnt - 6'd1;
            sda_oe <= ~id_bit;
          end
        end

        default: ;  // S_IDLE, S_WAIT: wait for START or STOP
      endcase
    end
  end

  wire _unused = &{scl, 1'b0};

endmodule
