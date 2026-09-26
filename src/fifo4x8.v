/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// 4 x 8-bit first-word-fall-through FIFO.
// Holds the request payload, then is reused for the response (half-duplex).
// A push while full is dropped (the caller flags overflow); a pop while empty
// is ignored. rdata reads 0x00 when empty, which gives the "pad with 0x00" rule.
module fifo4x8 (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       clr,    // synchronous clear, wins over push/pop
    input  wire       push,
    input  wire [7:0] wdata,
    input  wire       pop,
    output wire [7:0] rdata,  // head byte
    output wire       full,
    output wire       empty,
    output wire [2:0] count   // 0..4
);

  reg [7:0] mem[0:3];  // no reset: saves area; never read while empty
  reg [1:0] wp, rp;
  reg [2:0] cnt;

  wire do_pop  = pop & (cnt != 3'd0);
  wire do_push = push & ((cnt != 3'd4) | do_pop);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wp  <= 2'd0;
      rp  <= 2'd0;
      cnt <= 3'd0;
    end else if (clr) begin
      wp  <= 2'd0;
      rp  <= 2'd0;
      cnt <= 3'd0;
    end else begin
      if (do_push) wp <= wp + 2'd1;
      if (do_pop) rp <= rp + 2'd1;
      cnt <= cnt + {2'd0, do_push} - {2'd0, do_pop};
    end
  end

  always @(posedge clk) begin
    if (do_push && !clr) mem[wp] <= wdata;
  end

  assign empty = (cnt == 3'd0);
  assign full  = (cnt == 3'd4);
  assign count = cnt;
  assign rdata = empty ? 8'h00 : mem[rp];

endmodule
