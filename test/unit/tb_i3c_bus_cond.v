`default_nettype none
`timescale 1ns / 1ps

// Unit bench: I3C controller model -> synchroniser -> i3c_bus_cond.
module tb_i3c_bus_cond ();
  reg  clk;
  reg  rst_n;
  reg  i3c_scl_drv;
  reg  i3c_sda_oe;
  reg  i3c_sda_out;
  wire i3c_sda = ~(i3c_sda_oe & ~i3c_sda_out);  // pull-up when released

  wire [1:0] q, rise, fall;
  wire start, stop, hdr_exit;

  sync2_edge #(
      .N(2),
      .INIT(2'b11)
  ) u_sync (
      .clk  (clk),
      .rst_n(rst_n),
      .d    ({i3c_sda, i3c_scl_drv}),
      .q    (q),
      .rise (rise),
      .fall (fall)
  );

  i3c_bus_cond u_bus (
      .clk     (clk),
      .rst_n   (rst_n),
      .scl     (q[0]),
      .sda     (q[1]),
      .scl_rise(rise[0]),
      .sda_rise(rise[1]),
      .sda_fall(fall[1]),
      .start   (start),
      .stop    (stop),
      .hdr_exit(hdr_exit)
  );
endmodule
