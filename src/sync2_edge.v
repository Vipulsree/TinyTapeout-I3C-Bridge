/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Two-flop synchroniser with edge detection for N asynchronous inputs.
// Unfiltered bits: q is the second flop, rise/fall pulse in the cycle q changes.
// Filtered bits (FILTER=1): q only follows the input after two equal samples,
// so a one-sample glitch (<= 40 ns at 25 MHz) never reaches q.
module sync2_edge #(
    parameter integer N      = 1,
    parameter [N-1:0] INIT   = {N{1'b1}},  // reset level (idle-high buses)
    parameter [N-1:0] FILTER = {N{1'b0}}   // 1 = two-sample glitch filter
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire [N-1:0] d,     // raw pins
    output wire [N-1:0] q,     // synchronised level
    output wire [N-1:0] rise,  // one-cycle pulse: q went 0 -> 1
    output wire [N-1:0] fall   // one-cycle pulse: q went 1 -> 0
);

  reg [N-1:0] s1, s2, s3;  // synchroniser + one sample of history
  reg [N-1:0] lvl, lvl_d;  // filtered level and its previous value

  wire [N-1:0] agree = ~(s2 ^ s3);
  wire [N-1:0] lvl_n = (agree & s2) | (~agree & lvl);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      s1    <= INIT;
      s2    <= INIT;
      s3    <= INIT;
      lvl   <= INIT;
      lvl_d <= INIT;
    end else begin
      s1    <= d;
      s2    <= s1;
      s3    <= s2;
      lvl   <= lvl_n;
      lvl_d <= lvl;
    end
  end

  // Unfiltered bits use s2/s3 directly; filtered bits use lvl/lvl_d.
  // Synthesis removes lvl/lvl_d for bits whose FILTER is 0.
  assign q    = (FILTER & lvl) | (~FILTER & s2);
  assign rise = (FILTER & lvl & ~lvl_d) | (~FILTER & s2 & ~s3);
  assign fall = (FILTER & ~lvl & lvl_d) | (~FILTER & ~s2 & s3);

endmodule
