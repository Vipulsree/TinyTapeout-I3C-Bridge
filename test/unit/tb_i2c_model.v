`default_nettype none
`timescale 1ns / 1ps

// Bare open-drain I2C bus for checking the Python I2C models against each other.
module tb_i2c_model ();
  reg  ctrl_scl_pull;
  reg  ctrl_sda_pull;
  reg  tgt_sda_pull;
  wire scl = ~ctrl_scl_pull;
  wire sda = ~(ctrl_sda_pull | tgt_sda_pull);
endmodule
