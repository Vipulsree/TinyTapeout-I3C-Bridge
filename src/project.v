/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Track B: minimal I3C SDR target -> I2C controller bridge in one Tiny Tapeout tile.
// Pin map and protocol: docs/info.md and docs/architecture.md.
//
// Status (week 2): synchronisers and the I3C bus-condition detector are in place.
// Until i3c_tgt lands (weeks 4-5) the design drives nothing and DBG_STATE shows
// bus activity so the bus-condition logic can be checked on silicon-like pins.
module tt_um_i3cbridge (
    input  wire [7:0] ui_in,    // SA_LSB, PID_INST[1:0], I2C_FAST
    output wire [7:0] uo_out,   // DBG_STATE[3:0], DA_VALID, IRQ, BUSY, ERR
    input  wire [7:0] uio_in,   // I3C SCL/SDA (uio[2], uio[3]), I2C SCL/SDA (uio[6], uio[7])
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,   // 1 = output
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,      // 25 MHz
    input  wire       rst_n     // active-low reset
);

  // ----------------------------------------------------------- synchronisers
  // bit: 0 I3C_SCL, 1 I3C_SDA, 2 I2C_SCL, 3 I2C_SDA (all idle high)
  wire [3:0] pin_raw = {uio_in[7], uio_in[6], uio_in[3], uio_in[2]};
  wire [3:0] pin_q, pin_rise, pin_fall;

  sync2_edge #(
      .N     (4),
      .INIT  (4'b1111),
      .FILTER(4'b0000)
  ) u_sync (
      .clk  (clk),
      .rst_n(rst_n),
      .d    (pin_raw),
      .q    (pin_q),
      .rise (pin_rise),
      .fall (pin_fall)
  );

  // ----------------------------------------------------------- I3C bus conditions
  wire bus_start, bus_stop, hdr_exit;

  i3c_bus_cond u_bus (
      .clk     (clk),
      .rst_n   (rst_n),
      .scl     (pin_q[0]),
      .sda     (pin_q[1]),
      .scl_rise(pin_rise[0]),
      .sda_rise(pin_rise[1]),
      .sda_fall(pin_fall[1]),
      .start   (bus_start),
      .stop    (bus_stop),
      .hdr_exit(hdr_exit)
  );

  // ----------------------------------------------------------- scaffolding
  // Replaced by the target FSM state when i3c_tgt lands (M3, weeks 4-5):
  // DBG_STATE[0] = inside a transfer (START seen, no STOP yet)
  // DBG_STATE[2:1] = number of START / Sr conditions, modulo 4
  // DBG_STATE[3] = toggles on every HDR exit
  reg       in_xfer;
  reg [1:0] n_start;
  reg       hdr_tog;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      in_xfer <= 1'b0;
      n_start <= 2'd0;
      hdr_tog <= 1'b0;
    end else begin
      if (bus_start) begin
        in_xfer <= 1'b1;
        n_start <= n_start + 2'd1;
      end else if (bus_stop) begin
        in_xfer <= 1'b0;
      end
      if (hdr_exit) hdr_tog <= ~hdr_tog;
    end
  end

  // ----------------------------------------------------------- pins
  // ERR, BUSY, IRQ, DA_VALID stay low until the target and I2C controller exist.
  assign uo_out  = {4'b0000, hdr_tog, n_start, in_xfer};
  assign uio_out = 8'h00;
  assign uio_oe  = 8'h00;  // nothing is driven yet: I3C SDA and the I2C bus stay released

  wire _unused = &{ena, ui_in, uio_in[5:4], uio_in[1:0], pin_q[3:2], pin_rise[3:2], pin_fall[3:2],
                   pin_fall[0], 1'b0};

endmodule
