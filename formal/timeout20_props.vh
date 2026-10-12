// SPDX-License-Identifier: Apache-2.0
// Formal properties for timeout20 (part of plan property F4: the timer bounds
// every wait it watches). Included inside the module when FORMAL is defined.

reg fv_past = 1'b0;
always @(posedge clk) fv_past <= 1'b1;
initial assume (!rst_n);

// The limit is a design-time constant (TO_BUS in project.v). Alone, the module
// has a free limit input, so the proof assumes it; inside the design it is checked.
always @(posedge clk) begin
  if (fv_past) begin
`ifdef FV_UNIT_TIMEOUT20
    assume (limit == $past(limit));
`else
    assert (limit == $past(limit));
`endif
  end
end

// Cycles in a row, before this one, with run high, no kick and no expiry.
reg [W-1:0] fv_quiet;
always @(posedge clk or negedge rst_n) begin
  if (!rst_n) fv_quiet <= {W{1'b0}};
  else if (!run || kick || expired) fv_quiet <= {W{1'b0}};
  else fv_quiet <= fv_quiet + 1'b1;
end

always @(posedge clk) begin
  if (rst_n) begin
    assert (cnt == fv_quiet);
    // F4: a wait never lasts more than `limit` quiet cycles ...
    if (limit != {W{1'b0}}) assert (fv_quiet <= limit);
    // ... because the timer fires exactly when the limit is reached,
    assert (expired == (run && !kick && limit != {W{1'b0}} && fv_quiet == limit));
    // and a limit of 0 switches it off.
    if (limit == {W{1'b0}}) assert (!expired);
  end
  // expired is a one-cycle pulse: the count restarts from zero
  if (fv_past && rst_n && $past(rst_n) && $past(expired)) assert (!expired);
end

`ifndef FV_TOP  // too deep to reach through the pins: unit runs only
always @(posedge clk) begin
  if (rst_n) begin
    cover (expired && limit == 20'd5);
    cover (fv_past && $past(rst_n) && $past(fv_quiet) == 20'd3 && $past(kick) && limit == 20'd5);
  end
end
`endif
