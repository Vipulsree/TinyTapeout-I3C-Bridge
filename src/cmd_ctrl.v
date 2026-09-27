/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Transaction controller for the I3C -> I2C bridge.
// Private writes carry the command, the next private read returns the response:
//   IDLE -> HEADER -> WRITE -> EXEC -> RESPOND
//
// CMD[7:6] op: 00 write, 01 read, 10 write 1 byte then read, 11 status
// CMD[5:2] reserved, CMD[1:0] LEN-1, ADDR[6:0] downstream I2C address.
// Status byte: [7] I2C NACK, [6] I3C parity error, [5] FIFO overflow,
//              [4] timeout, [3] reserved (0), [2:0] FIFO count.
//
// One 20-bit inactivity timer covers two waits (docs/architecture.md, Timeouts):
//  - EXEC: the I2C transaction stalled -> pulse d_abort, respond with timeout set.
//  - otherwise, while the I3C target is mid-transfer: SCL stopped -> bus_timeout,
//    and the target releases SDA and goes back to IDLE.
module cmd_ctrl (
    input wire clk,
    input wire rst_n,

    // I3C target -> controller
    input wire [7:0] h_rx_data,
    input wire       h_rx_valid,     // one-cycle pulse per private-write byte (parity good)
    input wire       h_frame_start,  // own dynamic address ACKed
    input wire       h_frame_rd,     // with h_frame_start: 1 = private read
    input wire       h_frame_end,    // STOP or Sr after an ACKed private transfer
    input wire       par_err,        // I3C parity error (TE1 / TE2)

    // Controller -> I3C target (response)
    output wire [7:0] h_tx_data,  // current response byte
    output wire       h_tx_last,  // it is the last one: the target ends it with T = 0
    input  wire       h_tx_take,  // the target loaded h_tx_data
    output wire       can_read,   // a response is waiting: ACK DA/R
    output wire       can_write,  // no I2C transaction running: ACK DA/W

    // Controller -> I2C controller
    output reg        d_start,
    output reg  [1:0] d_op,
    output reg  [2:0] d_len,      // 1..4
    output reg  [6:0] d_addr,
    input  wire       d_done,
    input  wire       d_nack,
    output reg        d_abort,
    output wire [7:0] d_wr_data,  // FIFO head
    input  wire       d_wr_pop,
    input  wire [7:0] d_rd_data,
    input  wire       d_rd_push,

    // Timeout
    input  wire [19:0] to_limit,     // clock cycles, 0 disables
    input  wire        bus_active,   // I3C target is inside a transfer
    input  wire        bus_kick,     // an I3C SCL edge
    output wire        bus_timeout,  // one-cycle pulse: I3C bus stalled mid-transfer

    // Status
    output wire [2:0] state,  // 0 IDLE, 1 HEADER, 2 WRITE, 3 EXEC, 4 RESPOND
    output wire       irq,
    output wire       busy,
    output wire       err
);

  localparam [2:0] S_IDLE = 3'd0, S_HEADER = 3'd1, S_WRITE = 3'd2, S_EXEC = 3'd3, S_RESPOND = 3'd4;
  localparam [1:0] OP_WRITE = 2'd0, OP_READ = 2'd1, OP_WRRD = 2'd2, OP_STATUS = 2'd3;

  reg [2:0] st;
  reg [2:0] rem;         // payload bytes still expected, or response bytes still to send
  reg       exec_first;  // first cycle in EXEC
  reg       rsp_status;  // response is the status byte rather than FIFO data
  reg       reading;     // the controller has opened its private read
  reg f_nack, f_par, f_ovf, f_timeout;

  // ---------------------------------------------------------------- FIFO
  wire       fifo_full, fifo_empty;
  wire [2:0] fifo_count;
  wire [7:0] fifo_rdata;

  wire hdr_done  = (st == S_HEADER) & h_rx_valid;
  wire host_push = (st == S_WRITE) & h_rx_valid;
  wire dev_push  = (st == S_EXEC) & d_rd_push;
  wire fifo_push = host_push | dev_push;
  wire [7:0] fifo_wdata = host_push ? h_rx_data : d_rd_data;
  // Response bytes count only inside the private read (or as it opens).
  wire rsp_take = (st == S_RESPOND) & h_tx_take & (reading | (h_frame_start & h_frame_rd));
  wire rsp_pop  = rsp_take & ~rsp_status & (rem != 3'd0);
  wire fifo_pop = d_wr_pop | rsp_pop;
  wire ovf_evt  = fifo_push & fifo_full & ~fifo_pop;

  fifo4x8 u_fifo (
      .clk  (clk),
      .rst_n(rst_n),
      .clr  (hdr_done),
      .push (fifo_push),
      .wdata(fifo_wdata),
      .pop  (fifo_pop),
      .rdata(fifo_rdata),
      .full (fifo_full),
      .empty(fifo_empty),
      .count(fifo_count)
  );

  wire [7:0] status_byte = {f_nack, f_par, f_ovf, f_timeout, 1'b0, fifo_count};

  wire [2:0] pay_len = (d_op == OP_WRITE) ? d_len : (d_op == OP_WRRD) ? 3'd1 : 3'd0;
  wire rsp_is_status = (d_op == OP_WRITE) | (d_op == OP_STATUS);

  // ---------------------------------------------------------------- timeout
  wire in_exec = (st == S_EXEC);
  wire to_exp;

  timeout20 #(
      .W(20)
  ) u_timeout (
      .clk    (clk),
      .rst_n  (rst_n),
      .run    (in_exec | bus_active),
      .kick   (in_exec ? (d_wr_pop | d_rd_push | d_done | exec_first) : bus_kick),
      .limit  (to_limit),
      .expired(to_exp)
  );

  assign bus_timeout = to_exp & ~in_exec;

  // ---------------------------------------------------------------- FSM
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      st         <= S_IDLE;
      rem        <= 3'd0;
      exec_first <= 1'b0;
      rsp_status <= 1'b0;
      reading    <= 1'b0;
      d_start    <= 1'b0;
      d_abort    <= 1'b0;
      d_op       <= OP_WRITE;
      d_len      <= 3'd1;
      d_addr     <= 7'd0;
      f_nack     <= 1'b0;
      f_par      <= 1'b0;
      f_ovf      <= 1'b0;
      f_timeout  <= 1'b0;
    end else begin
      d_start <= 1'b0;
      d_abort <= 1'b0;

      case (st)
        S_IDLE:
        if (h_rx_valid) begin
          d_op  <= h_rx_data[7:6];
          d_len <= {1'b0, h_rx_data[1:0]} + 3'd1;
          st    <= S_HEADER;
        end

        S_HEADER:
        if (h_frame_end) st <= S_IDLE;  // private write ended before the header was complete
        else if (h_rx_valid) begin
          d_addr <= h_rx_data[6:0];
          if (d_op != OP_STATUS) begin
            f_nack    <= 1'b0;
            f_par     <= 1'b0;
            f_ovf     <= 1'b0;
            f_timeout <= 1'b0;
          end
          if (pay_len == 3'd0) begin
            st         <= S_EXEC;
            exec_first <= 1'b1;
          end else begin
            rem <= pay_len;
            st  <= S_WRITE;
          end
        end

        S_WRITE:
        if (h_frame_end) st <= S_IDLE;  // private write ended before the payload was complete
        else if (h_rx_valid) begin
          rem <= rem - 3'd1;
          if (rem == 3'd1) begin
            st         <= S_EXEC;
            exec_first <= 1'b1;
          end
        end

        S_EXEC: begin
          exec_first <= 1'b0;
          if (exec_first) begin
            if (d_op == OP_STATUS) begin
              st         <= S_RESPOND;
              rsp_status <= 1'b1;
              rem        <= 3'd1;
              reading    <= 1'b0;
            end else begin
              d_start <= 1'b1;
            end
          end else if (d_done || to_exp) begin
            st         <= S_RESPOND;
            rsp_status <= rsp_is_status;
            rem        <= rsp_is_status ? 3'd1 : d_len;
            reading    <= 1'b0;
            if (to_exp) begin
              d_abort   <= 1'b1;
              f_timeout <= 1'b1;
            end
          end
        end

        S_RESPOND: begin
          if (rsp_take && rem != 3'd0) rem <= rem - 3'd1;
          if (h_frame_start) begin
            if (h_frame_rd) reading <= 1'b1;
            else st <= S_IDLE;  // a new private write drops the unread response
          end else if (reading && h_frame_end) begin
            st <= S_IDLE;
          end
        end

        default: st <= S_IDLE;
      endcase

      // Error flags: a set event wins over the clear at HEADER.
      if (d_nack) f_nack <= 1'b1;
      if (par_err) f_par <= 1'b1;
      if (ovf_evt) f_ovf <= 1'b1;
    end
  end

  // ---------------------------------------------------------------- outputs
  assign state     = st;
  assign can_read  = (st == S_RESPOND);
  assign can_write = (st != S_EXEC);
  assign irq       = (st == S_RESPOND);
  assign busy      = (st == S_EXEC);
  assign err       = f_nack | f_par | f_ovf | f_timeout;
  assign h_tx_data = (st == S_RESPOND && rem != 3'd0) ? (rsp_status ? status_byte : fifo_rdata) : 8'h00;
  assign h_tx_last = (rem == 3'd1);
  assign d_wr_data = fifo_rdata;

  wire _unused = &{fifo_empty, 1'b0};

endmodule
