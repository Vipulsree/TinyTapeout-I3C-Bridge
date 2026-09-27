`default_nettype none
`timescale 1ns / 1ps

// Two bridges on one I3C bus, for ENTDAA arbitration (plan section 12:
// arbitration bugs only show up with more than one target). They differ only
// in their PID instance pins. Each has its own downstream I2C bus, pulled up.
module tb_two_bridges ();
  reg clk;
  reg rst_n;
  reg [1:0] inst_a;
  reg [1:0] inst_b;
  reg i3c_scl_drv;
  reg i3c_sda_oe;
  reg i3c_sda_out;

  wire [7:0] uo_a, uio_out_a, uio_oe_a;
  wire [7:0] uo_b, uio_out_b, uio_oe_b;

  // Low if anyone drives low; open-drain and push-pull highs never fight a low
  // in a correct design, which i3c_sda_conflict checks.
  wire a_low = uio_oe_a[3] & ~uio_out_a[3];
  wire b_low = uio_oe_b[3] & ~uio_out_b[3];
  wire a_high = uio_oe_a[3] & uio_out_a[3];
  wire b_high = uio_oe_b[3] & uio_out_b[3];
  wire ctl_low = i3c_sda_oe & ~i3c_sda_out;
  wire ctl_high = i3c_sda_oe & i3c_sda_out;
  wire i3c_sda = ~(ctl_low | a_low | b_low);
  wire i3c_sda_conflict = (ctl_high | a_high | b_high) & (ctl_low | a_low | b_low);

  wire [7:0] uio_in_a = {2'b11, 2'b00, i3c_sda, i3c_scl_drv, 2'b00};
  wire [7:0] uio_in_b = uio_in_a;

  tt_um_i3cbridge bridge_a (
      .ui_in  ({5'b00001, inst_a, 1'b0}),
      .uo_out (uo_a),
      .uio_in (uio_in_a),
      .uio_out(uio_out_a),
      .uio_oe (uio_oe_a),
      .ena    (1'b1),
      .clk    (clk),
      .rst_n  (rst_n)
  );

  tt_um_i3cbridge bridge_b (
      .ui_in  ({5'b00001, inst_b, 1'b0}),
      .uo_out (uo_b),
      .uio_in (uio_in_b),
      .uio_out(uio_out_b),
      .uio_oe (uio_oe_b),
      .ena    (1'b1),
      .clk    (clk),
      .rst_n  (rst_n)
  );
endmodule
