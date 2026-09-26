/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Tick generator for the downstream I2C clock.
// Quarter-period ticks: div_m1 = 62 (99.2 kHz) or 16 (367.6 kHz, meets the 1.3 us tLOW of fast mode).
module clkdiv #(
    parameter integer W = 6
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         en,      // 0 holds the counter at zero, so each burst starts in phase
    input  wire [W-1:0] div_m1,  // tick period - 1, in system clocks
    output wire         tick     // one-cycle pulse every div_m1 + 1 clocks while en
);

  reg [W-1:0] cnt;

  assign tick = en & (cnt == div_m1);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) cnt <= {W{1'b0}};
    else if (!en || tick) cnt <= {W{1'b0}};
    else cnt <= cnt + 1'b1;
  end

endmodule
