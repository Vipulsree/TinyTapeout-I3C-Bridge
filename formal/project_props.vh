// SPDX-License-Identifier: Apache-2.0
// Formal properties for the whole bridge (plan properties F2-F5 at the pins).
// Included inside tt_um_i3cbridge when FORMAL is defined. The properties of the
// sub-modules are included too, so formal/project.sby re-checks them in place.

reg fv_past = 1'b0;
always @(posedge clk) fv_past <= 1'b1;
initial assume (!rst_n);

wire [1:0] fv_drv = {uio_oe[3], uio_out[3]};  // I3C SDA pad: enable, value

always @(posedge clk) begin
  if (rst_n) begin
    // F5: the target never drives I3C SCL.
    assert (!uio_oe[2]);
    // Unused pads are never driven, and the I2C pads are open-drain (output 0).
    assert (uio_oe[1:0] == 2'b00 && uio_oe[5:4] == 2'b00);
    assert (uio_out[7:4] == 4'b0000 && uio_out[2:0] == 3'b000);

    // F2: the I3C SDA pad output is high only inside a private read (state 7); in
    // the open-drain phases (ACK = 2, ENTDAA identity = 4) it can only pull low.
    if (uio_out[3]) assert (uo_out[3:0] == 4'd7);
    if (uio_oe[3]) assert (uo_out[3:0] == 4'd2 || uo_out[3:0] == 4'd4 || uo_out[3:0] == 4'd7);
  end

  if (fv_past && rst_n && $past(rst_n)) begin
    // F3: the SDA pad changes only in the cycle after the synchronised SCL fell,
    // or releases at the End-of-Data hand-off / on START, STOP or a bus stall.
    if (fv_drv != $past(fv_drv)) begin
      assert ($past(pin_fall[0])
              || ($past(pin_rise[0]) && $past(tgt_state) == 4'd7 && fv_drv == 2'b00)
              || ($past(bus_start || bus_stop || bus_timeout) && fv_drv == 2'b00));
    end

    // F4: one cycle after STOP the target is in IDLE (0) with SDA released,
    // unless it is ignoring the bus in HDR (8).
    if ($past(bus_stop) && $past(tgt_state) != 4'd8) assert (tgt_state == 4'd0 && fv_drv == 2'b00);

    // The downstream I2C pads are released whenever the I2C controller is idle.
    if ($past(i2c_idle)) assert (uio_oe[7:6] == 2'b00);
    // BUSY is high exactly while the I2C transaction runs, and IRQ and BUSY never overlap.
    assert (!(uo_out[5] && uo_out[6]));
  end
end

always @(posedge clk) begin
  if (fv_past && rst_n && $past(rst_n)) begin
    cover (uio_oe[3] && uo_out[3:0] == 4'd2);  // the bridge ACKs the broadcast address
    cover (uo_out[3:0] == 4'd3);               // and receives a CCC
  end
end
