/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// General-purpose inactivity timeout (20-bit by default).
// Counts clock cycles while `run` is high; any `kick` restarts the count.
// `expired` pulses for one cycle once `limit` cycles pass with `run` high and
// no kick. A limit of 0 disables the timeout. At 25 MHz, 20 bits reach 41.9 ms.
module timeout20 #(
    parameter integer W = 20
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         run,      // count while high; the count clears while low
    input  wire         kick,     // activity seen: restart from zero
    input  wire [W-1:0] limit,    // timeout in clock cycles (0 = never)
    output wire         expired   // one-cycle pulse
);

  reg [W-1:0] cnt;

  assign expired = run & ~kick & (limit != {W{1'b0}}) & (cnt == limit);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) cnt <= {W{1'b0}};
    else if (!run || kick || expired) cnt <= {W{1'b0}};
    else cnt <= cnt + 1'b1;
  end

endmodule
