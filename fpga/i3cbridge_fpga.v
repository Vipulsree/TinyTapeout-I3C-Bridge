/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// tt_um_i3cbridge on any FPGA board, for the dry run when the Tiny Tapeout FPGA
// breakout is not at hand (docs/fpga_dry_run.md, option B).
//
// The design expects 25 MHz: the I2C rates (99.2 / 367.6 kHz) and the 35 ms
// timeout are counted in clock cycles. CLK_DIV divides the board clock:
//   1  the board clock is used as it is (25 MHz; 12 MHz also works, with the
//      I2C rates and the I3C limit halved and the timeout doubled)
//   2  50 MHz board   4  100 MHz board
//
// The bus pins are open-drain / push-pull pads built from uio_out and uio_oe,
// as the Tiny Tapeout mux does. I3C SDA and both I2C lines need pull-ups
// (external resistors or the FPGA's pad pull-ups in the constraints file).
module i3cbridge_fpga #(
    parameter integer CLK_DIV = 1
) (
    input  wire       clk_board,
    input  wire       rst_n,     // active low
    input  wire       i3c_scl,   // uio[2], from the I3C controller
    inout  wire       i3c_sda,   // uio[3]
    inout  wire       i2c_scl,   // uio[6]
    inout  wire       i2c_sda,   // uio[7]
    input  wire [1:0] pid_inst,  // ui_in[2:1]; tie to 0 if unused
    input  wire       i2c_fast,  // ui_in[3]: 0 = 99.2 kHz, 1 = 367.6 kHz
    output wire [7:0] status     // uo_out: DBG_STATE[3:0], DA_VALID, IRQ, BUSY, ERR
);

  // ----------------------------------------------------------- clock
  wire clk;
  generate
    if (CLK_DIV <= 1) begin : g_direct
      assign clk = clk_board;
    end else begin : g_div
      // Toggle flip-flop chain; fine for a dry run (the tools put it on a clock net).
      reg [7:0] div = 8'd0;
      always @(posedge clk_board) div <= div + 8'd1;
      assign clk = (CLK_DIV == 2) ? div[0] : (CLK_DIV == 4) ? div[1] : div[2];
    end
  endgenerate

  // ----------------------------------------------------------- design
  wire [7:0] uio_out, uio_oe;
  wire [7:0] uio_in = {i2c_sda, i2c_scl, 2'b00, i3c_sda, i3c_scl, 2'b00};

  tt_um_i3cbridge u_bridge (
      .ui_in  ({4'b0000, i2c_fast, pid_inst, 1'b0}),
      .uo_out (status),
      .uio_in (uio_in),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (1'b1),
      .clk    (clk),
      .rst_n  (rst_n)
  );

  // ----------------------------------------------------------- pads
  assign i3c_sda = uio_oe[3] ? uio_out[3] : 1'bz;  // open-drain low or push-pull
  assign i2c_scl = uio_oe[6] ? uio_out[6] : 1'bz;  // uio_out[7:6] is always 0: open-drain
  assign i2c_sda = uio_oe[7] ? uio_out[7] : 1'bz;

endmodule
