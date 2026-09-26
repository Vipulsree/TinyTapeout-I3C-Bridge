/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// I3C bus-condition detector (works on synchronised SCL/SDA).
//  start    : SDA fell while SCL high (START or repeated START), one-cycle pulse
//  stop     : SDA rose while SCL high, one-cycle pulse
//  hdr_exit : one-cycle pulse on the 4th SDA falling edge while SCL stays low
//             (HDR Exit Pattern). SDR traffic changes SDA at most once per SCL
//             low phase, so it never reaches 4. The Target Reset Pattern also
//             contains 4+ falls with SCL low; treating it as an HDR exit is harmless.
module i3c_bus_cond (
    input  wire clk,
    input  wire rst_n,
    input  wire scl,       // synchronised levels
    input  wire sda,
    input  wire scl_rise,  // one-cycle edge pulses from the synchroniser
    input  wire sda_rise,
    input  wire sda_fall,
    output wire start,
    output wire stop,
    output reg  hdr_exit
);

  assign start = sda_fall & scl;
  assign stop  = sda_rise & scl;

  reg [1:0] nfall;  // SDA falls seen in the current SCL-low phase (0..3)

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      nfall    <= 2'd0;
      hdr_exit <= 1'b0;
    end else begin
      hdr_exit <= 1'b0;
      if (scl || scl_rise) begin
        nfall <= 2'd0;
      end else if (sda_fall) begin
        if (nfall == 2'd3) begin
          hdr_exit <= 1'b1;
          nfall    <= 2'd0;
        end else begin
          nfall <= nfall + 2'd1;
        end
      end
    end
  end

  wire _unused = &{sda, 1'b0};

endmodule
