/*
 * Copyright (c) 2026 VLSI PD Tapeout team
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Track B: minimal I3C SDR target -> I2C controller bridge in one Tiny Tapeout tile.
// Pin map and protocol: docs/info.md and docs/architecture.md.
//
// An I3C controller assigns the bridge a dynamic address with ENTDAA, then
// sends a command in a private write. cmd_ctrl runs
// it on the downstream I2C bus with i2c_ctrl, and the next private read returns
// the data or a status byte.
module tt_um_i3cbridge (
    input  wire [7:0] ui_in,    // PID_INST[1:0] (ui_in[2:1]), I2C_FAST (ui_in[3])
    output wire [7:0] uo_out,   // DBG_STATE[3:0], DA_VALID, IRQ, BUSY, ERR
    input  wire [7:0] uio_in,   // I3C SCL/SDA (uio[2], uio[3]), I2C SCL/SDA (uio[6], uio[7])
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,   // 1 = output
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,      // 25 MHz
    input  wire       rst_n     // active-low reset
);

  // ----------------------------------------------------------- timeouts
  // 20-bit count of 25 MHz clocks (max 1,048,575 = 41.9 ms); 0 disables.
  // 35 ms is the SMBus tTIMEOUT maximum: it bounds a downstream I2C transaction
  // (including clock stretching) and an I3C transfer whose SCL stops mid-way.
  localparam [19:0] TO_BUS = 20'd875_000;

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

  // ----------------------------------------------------------- I3C target
  wire       i3c_sda_oe, i3c_sda_out;
  wire [5:0] id_idx;
  wire       id_bit, set_da, clr_da, da_valid;
  wire [6:0] da, new_da;
  wire [7:0] h_rx_data, h_tx_data;
  wire       h_rx_valid, h_frame_start, h_frame_rd, h_frame_end, h_tx_last, h_tx_take;
  wire       can_read, can_write, par_err, tgt_active, bus_timeout;
  wire [3:0] tgt_state;

  i3c_tgt u_tgt (
      .clk        (clk),
      .rst_n      (rst_n),
      .scl        (pin_q[0]),
      .sda        (pin_q[1]),
      .scl_rise   (pin_rise[0]),
      .scl_fall   (pin_fall[0]),
      .start      (bus_start),
      .stop       (bus_stop),
      .hdr_exit   (hdr_exit),
      .timeout    (bus_timeout),
      .sda_oe     (i3c_sda_oe),
      .sda_out    (i3c_sda_out),
      .id_idx     (id_idx),
      .id_bit     (id_bit),
      .da         (da),
      .da_valid   (da_valid),
      .set_da     (set_da),
      .new_da     (new_da),
      .clr_da     (clr_da),
      .rx_data    (h_rx_data),
      .rx_valid   (h_rx_valid),
      .frame_start(h_frame_start),
      .frame_rd   (h_frame_rd),
      .frame_end  (h_frame_end),
      .tx_data    (h_tx_data),
      .tx_last    (h_tx_last),
      .tx_take    (h_tx_take),
      .can_read   (can_read),
      .can_write  (can_write),
      .par_err    (par_err),
      .active     (tgt_active),
      .state      (tgt_state)
  );

  i3c_daa u_daa (
      .clk     (clk),
      .rst_n   (rst_n),
      .inst    (ui_in[2:1]),
      .id_idx  (id_idx),
      .id_bit  (id_bit),
      .set_da  (set_da),
      .new_da  (new_da),
      .clr_da  (clr_da),
      .da      (da),
      .da_valid(da_valid)
  );

  // ----------------------------------------------------------- controller
  wire [7:0] d_wr_data, d_rd_data;
  wire [1:0] d_op;
  wire [2:0] d_len, ctrl_state;
  wire [6:0] d_addr;
  wire       d_start, d_done, d_nack, d_abort, d_wr_pop, d_rd_push;
  wire       irq, busy, err;

  cmd_ctrl u_ctrl (
      .clk          (clk),
      .rst_n        (rst_n),
      .h_rx_data    (h_rx_data),
      .h_rx_valid   (h_rx_valid),
      .h_frame_start(h_frame_start),
      .h_frame_rd   (h_frame_rd),
      .h_frame_end  (h_frame_end),
      .par_err      (par_err),
      .h_tx_data    (h_tx_data),
      .h_tx_last    (h_tx_last),
      .h_tx_take    (h_tx_take),
      .can_read     (can_read),
      .can_write    (can_write),
      .d_start      (d_start),
      .d_op         (d_op),
      .d_len        (d_len),
      .d_addr       (d_addr),
      .d_done       (d_done),
      .d_nack       (d_nack),
      .d_abort      (d_abort),
      .d_wr_data    (d_wr_data),
      .d_wr_pop     (d_wr_pop),
      .d_rd_data    (d_rd_data),
      .d_rd_push    (d_rd_push),
      .to_limit     (TO_BUS),
      .bus_active   (tgt_active),
      .bus_kick     (pin_rise[0] | pin_fall[0]),
      .bus_timeout  (bus_timeout),
      .state        (ctrl_state),
      .irq          (irq),
      .busy         (busy),
      .err          (err)
  );

  // ----------------------------------------------------------- downstream I2C
  // I2C_FAST is sampled only between transactions.
  reg i2c_fast;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) i2c_fast <= 1'b0;
    else if (!busy) i2c_fast <= ui_in[3];
  end

  wire tick_en, tick, i2c_scl_low, i2c_sda_low, i2c_idle;

  clkdiv #(
      .W(6)
  ) u_div (
      .clk   (clk),
      .rst_n (rst_n),
      .en    (tick_en),
      .div_m1(i2c_fast ? 6'd16 : 6'd62),  // quarter periods: 367.6 kHz / 99.2 kHz
      .tick  (tick)
  );

  i2c_ctrl u_i2c (
      .clk      (clk),
      .rst_n    (rst_n),
      .scl      (pin_q[2]),
      .sda      (pin_q[3]),
      .scl_low  (i2c_scl_low),
      .sda_low  (i2c_sda_low),
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
      .idle     (i2c_idle)
  );

  // ----------------------------------------------------------- pins
  assign uo_out = {err, busy, irq, da_valid, tgt_state};

  // uio: 2 I3C SCL (input only), 3 I3C SDA, 6 I2C SCL, 7 I2C SDA (open-drain: out = 0)
  assign uio_out = {4'b0000, i3c_sda_out, 3'b000};
  assign uio_oe  = {i2c_sda_low, i2c_scl_low, 2'b00, i3c_sda_oe, 3'b000};

  wire _unused = &{ena, ui_in[7:4], ui_in[0], uio_in[5:4], uio_in[1:0], pin_rise[3:2], pin_fall[3:2],
                   ctrl_state, i2c_idle, 1'b0};

endmodule
