// SPDX-License-Identifier: Apache-2.0
// Formal properties for i2c_ctrl: basic safety of the downstream controller.
// Included inside the module when FORMAL is defined.

reg fv_past = 1'b0;
always @(posedge clk) fv_past <= 1'b1;
initial assume (!rst_n);

always @(posedge clk) begin
  if (rst_n) begin
    assert (st <= C_STOP);    // only the six encoded states
    assert (bcnt <= 4'd8);    // 8 data bits, then the ACK slot
    if (d_nack) assert (d_done);
    if (d_done) assert (st == C_IDLE);
    if (d_wr_pop) assert (st == C_ADDR || st == C_WR);
    if (d_rd_push) assert (st == C_RD);
    if (tick_en) assert (st != C_IDLE);
  end

  if (fv_past && rst_n && $past(rst_n)) begin
    // An idle controller lets go of both lines (the drivers are one clock behind).
    if ($past(st) == C_IDLE) assert (!scl_low && !sda_low);
    // d_done is a one-cycle pulse.
    if ($past(d_done)) assert (!d_done);
    // An abort always leads to STOP, never to d_done.
    if ($past(d_abort) && $past(st) != C_IDLE) assert (st == C_STOP && aborting);
    if (d_done) assert (!$past(aborting));
  end
end

// Reachability (a whole transaction is too many ticks for a quick cover run; the
// cocotb suite covers those): the address goes out, and an abort reaches STOP.
`ifndef FV_TOP  // too deep to reach through the pins: unit runs only
always @(posedge clk) begin
  if (fv_past && rst_n && $past(rst_n)) begin
    cover (st == C_ADDR && bcnt == 4'd2);
    cover (st == C_STOP && aborting && ph == PC);
  end
end
`endif
