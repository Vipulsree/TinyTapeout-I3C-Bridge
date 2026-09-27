/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Downstream I2C controller. Runs one cmd_ctrl transaction per d_start:
//   write (op 0)           S, addr+W, d_len bytes from the FIFO, P
//   read (op 1)            S, addr+R, d_len bytes into the FIFO (ACK all but the last), P
//   write then read (op 2) S, addr+W, 1 byte, Sr, addr+R, d_len bytes, P
// A NACK anywhere sends STOP and pulses d_nack with d_done. d_abort (timeout)
// finishes with STOP without waiting for a stretched clock, and no d_done.
//
// Every START, STOP and bit is one symbol of four quarter periods (clkdiv ticks):
//   A  SCL low, SDA changes | B  SCL released; waits while a device stretches it
//   C  SCL high             | D  SCL pulled low
// SDA is sampled at the B -> C tick. Both lines are open-drain (the controller
// only pulls low) and the drivers are registered, one clock behind the phase:
// the decode glitches between states, and a glitch on SCL or SDA is a clock
// edge or a START.
module i2c_ctrl (
    input wire clk,
    input wire rst_n,

    // Synchronised bus
    input wire scl,
    input wire sda,

    // Open-drain pull-downs
    output reg scl_low,
    output reg sda_low,

    // clkdiv (quarter-period ticks)
    output wire tick_en,
    input  wire tick,

    // cmd_ctrl
    input  wire       d_start,
    input  wire [1:0] d_op,
    input  wire [2:0] d_len,
    input  wire [6:0] d_addr,
    input  wire       d_abort,
    input  wire [7:0] d_wr_data,
    output wire       d_wr_pop,
    output wire [7:0] d_rd_data,
    output wire       d_rd_push,
    output reg        d_done,
    output reg        d_nack,

    output wire idle
);

  localparam [1:0] OP_READ = 2'd1, OP_WRRD = 2'd2;
  localparam [2:0] C_IDLE = 3'd0, C_START = 3'd1, C_ADDR = 3'd2, C_WR = 3'd3, C_RD = 3'd4,
                   C_STOP = 3'd5;
  localparam [1:0] PA = 2'd0, PB = 2'd1, PC = 2'd2, PD = 2'd3;

  reg [2:0] st;
  reg [1:0] ph;
  reg [7:0] sh;
  reg [3:0] bcnt;     // bits of the current byte, 8 = ACK slot
  reg [2:0] cnt;      // bytes left in this phase, including the current one
  reg       started;  // bus owned: START sent, STOP not yet
  reg       second;   // write-then-read: now in the read phase after Sr
  reg       nacked;
  reg       aborting;
  reg       samp;     // SDA sampled at the B -> C tick

  wire on      = (st != C_IDLE);
  wire hold    = (ph == PB) & ~scl & ~aborting;  // a device is stretching SCL
  wire symend  = on & tick & (ph == PD);
  wire ackbit  = (bcnt == 4'd8);
  wire last    = (cnt == 3'd1);
  wire rnw     = (d_op == OP_READ) | second;
  wire bytes   = (st == C_ADDR) | (st == C_WR) | (st == C_RD);
  wire acked   = bytes & symend & ackbit & ~samp;

  // Level put on SDA in a data symbol (1 = released): reads release the data
  // bits and ACK every byte but the last.
  wire bit_out = (st == C_RD) ? ~(ackbit & ~last) : (ackbit | sh[7]);

  wire scl_low_n = on & (((ph == PA) & ((st != C_START) | started)) | ((ph == PD) & (st != C_STOP)));
  wire sda_low_n = on & ((st == C_START) ? ph[1] :           // C, D
                         (st == C_STOP)  ? ~ph[1] : ~bit_out);  // A, B

  assign tick_en   = on & ~hold;
  assign d_wr_pop  = acked & (((st == C_ADDR) & ~rnw) | ((st == C_WR) & ~last));
  assign d_rd_push = symend & (st == C_RD) & (bcnt == 4'd7);
  assign d_rd_data = {sh[6:0], samp};
  assign idle      = ~on;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st       <= C_IDLE;
      ph       <= PA;
      sh       <= 8'h00;
      bcnt     <= 4'd0;
      cnt      <= 3'd0;
      started  <= 1'b0;
      second   <= 1'b0;
      nacked   <= 1'b0;
      aborting <= 1'b0;
      samp     <= 1'b1;
      scl_low  <= 1'b0;
      sda_low  <= 1'b0;
      d_done   <= 1'b0;
      d_nack   <= 1'b0;
    end else begin
      d_done  <= 1'b0;
      d_nack  <= 1'b0;
      scl_low <= scl_low_n;
      sda_low <= sda_low_n;

      if (d_abort) begin
        if (on) begin
          st       <= C_STOP;
          ph       <= PA;
          aborting <= 1'b1;
        end
      end else if (d_start) begin
        st       <= C_START;
        ph       <= PA;
        cnt      <= (d_op == OP_WRRD) ? 3'd1 : d_len;
        started  <= 1'b0;
        second   <= 1'b0;
        nacked   <= 1'b0;
        aborting <= 1'b0;
      end else if (on && tick) begin
        ph <= ph + 2'd1;
        if (ph == PB) samp <= sda;
        if (ph == PD) begin
          case (st)
            C_START: begin
              started <= 1'b1;
              st      <= C_ADDR;
              bcnt    <= 4'd0;
              sh      <= {d_addr, rnw};
            end
            C_ADDR, C_WR, C_RD:
            if (!ackbit) begin
              sh   <= {sh[6:0], samp};
              bcnt <= bcnt + 4'd1;
            end else begin
              bcnt <= 4'd0;
              if (st != C_RD && samp) begin  // address or data NACKed
                nacked <= 1'b1;
                st     <= C_STOP;
              end else if (st == C_ADDR) begin
                if (rnw) st <= C_RD;
                else begin
                  st <= C_WR;
                  sh <= d_wr_data;
                end
              end else if (!last) begin
                cnt <= cnt - 3'd1;
                if (st == C_WR) sh <= d_wr_data;
              end else if (st == C_WR && d_op == OP_WRRD && !second) begin
                second <= 1'b1;  // repeated START, then the read phase
                cnt    <= d_len;
                st     <= C_START;
              end else begin
                st <= C_STOP;
              end
            end
            C_STOP: begin
              st      <= C_IDLE;
              started <= 1'b0;
              if (!aborting) begin
                d_done <= 1'b1;
                d_nack <= nacked;
              end
            end
            default: st <= C_IDLE;
          endcase
        end
      end
    end
  end

endmodule
