`default_nettype none
`timescale 1ns / 1ps

/* Testbench wrapper for tt_um_i3cbridge.
   - I3C bus on uio[2] (SCL) and uio[3] (SDA). The test's I3C controller model
     drives SCL push-pull and SDA open-drain or push-pull; SDA has a pull-up.
     i3c_sda_conflict flags two drivers fighting (one high, one low).
   - Downstream I2C bus on uio[6] (SCL) and uio[7] (SDA): open-drain with
     pull-ups; an external device pulls low through i2c_scl_pull / i2c_sda_pull.
   - Other bidirectional pins loop the design's output back when it drives them.
*/
module tb ();

  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
    #1;
  end

  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  reg [7:0] uio_in_drv;
  // I3C controller model
  reg i3c_scl_drv;
  reg i3c_sda_oe;
  reg i3c_sda_out;
  // External I2C device
  reg i2c_scl_pull;
  reg i2c_sda_pull;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;
  wire [7:0] uio_in;
`ifdef GL_TEST
  wire VPWR = 1'b1;
  wire VGND = 1'b0;
`endif

  // I3C SDA: low if anyone drives low, else high (push-pull high or pull-up)
  wire i3c_sda = ~((i3c_sda_oe & ~i3c_sda_out) | (uio_oe[3] & ~uio_out[3]));
  wire i3c_sda_conflict = i3c_sda_oe & uio_oe[3] & (i3c_sda_out != uio_out[3]);
  wire i3c_scl_driven = uio_oe[2];  // a target must never drive SCL in SDR

  // Downstream I2C: open-drain with pull-ups
  wire i2c_scl = ~((uio_oe[6] & ~uio_out[6]) | i2c_scl_pull);
  wire i2c_sda = ~((uio_oe[7] & ~uio_out[7]) | i2c_sda_pull);
  wire i2c_push_pull_violation = (uio_oe[6] & uio_out[6]) | (uio_oe[7] & uio_out[7]);

  wire [7:0] loop = (uio_oe & uio_out) | (~uio_oe & uio_in_drv);
  assign uio_in = {i2c_sda, i2c_scl, loop[5:4], i3c_sda, i3c_scl_drv, loop[1:0]};

  tt_um_i3cbridge user_project (
`ifdef GL_TEST
      .VPWR(VPWR),
      .VGND(VGND),
`endif
      .ui_in  (ui_in),
      .uo_out (uo_out),
      .uio_in (uio_in),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (ena),
      .clk    (clk),
      .rst_n  (rst_n)
  );

endmodule
