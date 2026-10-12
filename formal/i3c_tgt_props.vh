// SPDX-License-Identifier: Apache-2.0
// Formal properties for i3c_tgt (plan properties F2, F3 and F4). Included inside
// the module when FORMAL is defined.

reg fv_past = 1'b0;
always @(posedge clk) fv_past <= 1'b1;
initial assume (!rst_n);

// The synchroniser never reports a rising and a falling SCL edge in one cycle.
// Alone, the module has free inputs, so the proof assumes it; inside the design
// (formal/project.sby) the same condition is checked instead.
always @(*) begin
`ifdef FV_UNIT_I3C_TGT
  assume (!(scl_rise && scl_fall));
`else
  assert (!(scl_rise && scl_fall));
`endif
end

wire [1:0] fv_drv = {sda_oe, sda_out};

always @(posedge clk) begin
  if (rst_n) begin
    assert (st <= S_WAIT);  // only the ten encoded states

    // F2: push-pull only inside a private read. Anywhere else the pad output is 0,
    // so the open-drain phases (ACK, ENTDAA identity) can only pull SDA low.
    if (sda_out) assert (st == S_PRIV_RD);
    // The target drives SDA in three states only.
    if (sda_oe) assert (st == S_ACK || st == S_DAA_ID || st == S_PRIV_RD);
  end

  if (fv_past && rst_n && $past(rst_n)) begin
    // F3: the SDA drive (enable or value) changes only in the cycle after SCL
    // fell, with two exceptions that only ever release the line: the End-of-Data
    // hand-off as SCL rises in a read T-bit, and START / STOP / bus stall.
    if (fv_drv != $past(fv_drv)) begin
      assert ($past(scl_fall)
              || ($past(scl_rise) && $past(st) == S_PRIV_RD && $past(cnt) == 6'd8 && fv_drv == 2'b00)
              || ($past(bus_ev) && fv_drv == 2'b00));
    end

    // F4: one cycle after STOP or a bus-stall timeout the target is in IDLE with
    // SDA released (HDR ignores both and leaves only through the exit pattern).
    if ($past(stop || timeout) && $past(st) != S_HDR) assert (st == S_IDLE && fv_drv == 2'b00);
    if ($past(st) == S_HDR) assert (st == S_HDR || (st == S_IDLE && $past(hdr_exit)));
    // START always restarts the address phase.
    if ($past(start) && !$past(stop || timeout) && $past(st) != S_HDR) assert (st == S_ADDR && fv_drv == 2'b00);
  end
end

// Reachability: the solver finds traces that drive push-pull, hand SDA back and
// enter HDR. (ENTDAA needs more cycles than a quick cover run; the cocotb suite
// exercises it, with one bridge and with two.)
`ifndef FV_TOP  // too deep to reach through the pins: unit runs only
always @(posedge clk) begin
  if (fv_past && rst_n && $past(rst_n)) begin
    cover (st == S_PRIV_RD && sda_oe && sda_out);
    cover ($past(st) == S_PRIV_RD && $past(sda_oe) && !sda_oe && $past(scl_rise) && st == S_PRIV_RD);
    cover (st == S_HDR);
  end
end
`endif
