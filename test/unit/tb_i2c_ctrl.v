`default_nettype none
`timescale 1ns / 1ps

// i2c_ctrl on an open-drain bus with pull-ups, behind the same synchroniser and
// divider as in project.v. The test plays cmd_ctrl; the Python I2C target model
// (or the test, to stretch the clock) pulls the lines through ext_*_pull.
module tb_i2c_ctrl (
    input wire clk,
    input wire rst_n,
    input wire fast,
    input wire ext_scl_pull,
    input wire ext_sda_pull,
    input wire d_start,
    input wire [1:0] d_op,
    input wire [2:0] d_len,
    input wire [6:0] d_addr,
    input wire d_abort,
    input wire [7:0] d_wr_data
);
  wire scl_low, sda_low;
  wire scl = ~(scl_low | ext_scl_pull);
  wire sda = ~(sda_low | ext_sda_pull);

  wire [1:0] q, rise, fall;
  sync2_edge #(
      .N     (2),
      .INIT  (2'b11),
      .FILTER(2'b00)
  ) u_sync (
      .clk  (clk),
      .rst_n(rst_n),
      .d    ({sda, scl}),
      .q    (q),
      .rise (rise),
      .fall (fall)
  );

  wire tick_en, tick;
  clkdiv #(
      .W(6)
  ) u_div (
      .clk   (clk),
      .rst_n (rst_n),
      .en    (tick_en),
      .div_m1(fast ? 6'd16 : 6'd62),
      .tick  (tick)
  );

  wire [7:0] d_rd_data;
  wire d_wr_pop, d_rd_push, d_done, d_nack, idle;

  i2c_ctrl dut (
      .clk      (clk),
      .rst_n    (rst_n),
      .scl      (q[0]),
      .sda      (q[1]),
      .scl_low  (scl_low),
      .sda_low  (sda_low),
      .tick_en  (tick_en),
      .tick     (tick),
      .d_start  (d_start),
      .d_op     (d_op),
      .d_len    (d_len),
      .d_addr   (d_addr),
      .d_abort  (d_abort),
      .d_wr_data(d_wr_data),
      .d_wr_pop (d_wr_pop),
      .d_rd_data(d_rd_data),
      .d_rd_push(d_rd_push),
      .d_done   (d_done),
      .d_nack   (d_nack),
      .idle     (idle)
  );

  wire _unused = &{rise, fall, 1'b0};
endmodule
