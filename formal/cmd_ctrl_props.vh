// SPDX-License-Identifier: Apache-2.0
// Formal properties for cmd_ctrl (plan property F4: the timeout ends a stalled
// I2C transaction). Included inside the module when FORMAL is defined.

reg fv_past = 1'b0;
always @(posedge clk) fv_past <= 1'b1;
initial assume (!rst_n);

`ifdef FV_UNIT_CMD_CTRL
// Alone, the timeout limit is a free input: hold it constant like TO_BUS.
always @(posedge clk) if (fv_past) assume (to_limit == $past(to_limit));
`endif

always @(posedge clk) begin
  if (rst_n) begin
    assert (st <= S_RESPOND);  // only the five encoded states

    // Lengths stay in range, so no counter wraps.
    if (st != S_IDLE) assert (d_len >= 3'd1 && d_len <= 3'd4);
    assert (rem <= 3'd4);
    if (st == S_WRITE) assert (rem != 3'd0);

    // The I2C controller is started only from EXEC, and aborted only on the way out.
    if (d_start) assert (st == S_EXEC);
    if (d_abort) assert (st == S_RESPOND && f_timeout);

    // The I3C stall timeout is never raised while an I2C transaction runs.
    if (bus_timeout) assert (st != S_EXEC);
  end

  if (fv_past && rst_n && $past(rst_n)) begin
    // F4: when the timer expires in EXEC, the next cycle the bridge is in
    // RESPOND with the timeout flag set and the I2C transfer aborted.
    if ($past(st) == S_EXEC && $past(to_exp)) assert (st == S_RESPOND && d_abort && f_timeout);
    // EXEC ends only through d_done, a status command or the timeout.
    if ($past(st) == S_EXEC && st != S_EXEC)
      assert (st == S_RESPOND && ($past(d_done) || $past(to_exp) || ($past(exec_first) && $past(d_op) == OP_STATUS)));
    // d_start and d_abort are one-cycle pulses.
    if ($past(d_start)) assert (!d_start);
    if ($past(d_abort)) assert (!d_abort);
  end
end

`ifndef FV_TOP  // too deep to reach through the pins: unit runs only
always @(posedge clk) begin
  if (fv_past && rst_n && $past(rst_n)) begin
    cover (d_abort);                                   // a stalled I2C transaction timed out
    cover ($past(st) == S_EXEC && st == S_RESPOND && !f_timeout && !rsp_status);  // a read completed
    cover (bus_timeout);
  end
end
`endif
