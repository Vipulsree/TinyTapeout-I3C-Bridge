/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Dynamic address register and the 64-bit identity sent during ENTDAA.
// The identity is constant apart from the two instance pins, so the "shifter"
// is just a bit select driven by i3c_tgt's bit counter.
//
//   PID[47:33] MIPI manufacturer ID  0x7FFF (placeholder: no MIPI-assigned ID)
//   PID[32]    ID type selector      0 (fixed value)
//   PID[31:16] part ID               0x0001
//   PID[15:12] instance ID           {2'b00, inst}
//   PID[11:0]  vendor defined        0x000
//   BCR 0x01 (target, max data speed limitation), DCR 0x00 (generic)
// Values proposed in docs/architecture.md; confirm with the team before tapeout.
module i3c_daa (
    input wire clk,
    input wire rst_n,

    input  wire [1:0] inst,    // PID instance bits (PID_INST pins)
    input  wire [5:0] id_idx,  // 63 = PID[47] ... 0 = DCR[0]
    output wire       id_bit,

    input  wire       set_da,  // ENTDAA assigned an address
    input  wire [6:0] new_da,
    input  wire       clr_da,  // RSTDAA
    output reg  [6:0] da,
    output reg        da_valid
);

  localparam [14:0] MANUF_ID = 15'h7FFF;
  localparam [15:0] PART_ID = 16'h0001;
  localparam [7:0] BCR = 8'h01;
  localparam [7:0] DCR = 8'h00;

  wire [63:0] ident = {MANUF_ID, 1'b0, PART_ID, 2'b00, inst, 12'h000, BCR, DCR};
  assign id_bit = ident[id_idx];

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      da       <= 7'd0;
      da_valid <= 1'b0;
    end else if (clr_da) begin
      da_valid <= 1'b0;
    end else if (set_da) begin
      da       <= new_da;
      da_valid <= 1'b1;
    end
  end

endmodule
