// SPDX-License-Identifier: Apache-2.0
// Formal properties for fifo4x8 (plan property F1). Included inside the module
// when FORMAL is defined (read_verilog -formal); see formal/README.md.
//
// F1: the count never exceeds 4 and never underflows. On top of that the FIFO is
// checked against a 4-entry shift-register model, so bytes come out in the order
// they went in and an empty FIFO reads 0x00.

reg fv_past = 1'b0;
always @(posedge clk) fv_past <= 1'b1;
initial assume (!rst_n);

// ---------------------------------------------------------------- reference model
// fv_q0 is the head. A push while full is dropped unless a pop frees a slot in the
// same cycle; a pop while empty is ignored; clr wins.
reg [7:0] fv_q0, fv_q1, fv_q2, fv_q3;
reg [2:0] fv_n;

wire       fv_pop  = pop & (fv_n != 3'd0);
wire       fv_push = push & ((fv_n != 3'd4) | fv_pop);
wire [2:0] fv_n_popped = fv_n - {2'd0, fv_pop};

always @(posedge clk or negedge rst_n) begin
  if (!rst_n) fv_n <= 3'd0;
  else if (clr) fv_n <= 3'd0;
  else fv_n <= fv_n_popped + {2'd0, fv_push};
end

always @(posedge clk) begin
  if (rst_n && !clr) begin
    if (fv_pop) begin
      fv_q0 <= fv_q1;
      fv_q1 <= fv_q2;
      fv_q2 <= fv_q3;
    end
    if (fv_push) begin
      case (fv_n_popped)
        3'd0: fv_q0 <= wdata;
        3'd1: fv_q1 <= wdata;
        3'd2: fv_q2 <= wdata;
        default: fv_q3 <= wdata;
      endcase
    end
  end
end

// Stored bytes, oldest first
wire [7:0] fv_s0 = mem[rp];
wire [7:0] fv_s1 = mem[rp+2'd1];
wire [7:0] fv_s2 = mem[rp+2'd2];
wire [7:0] fv_s3 = mem[rp+2'd3];

always @(posedge clk) begin
  if (rst_n) begin
    // F1: the count stays in 0..4
    assert (cnt <= 3'd4);
    // pointers and count agree (count 0 and count 4 both have wp == rp)
    assert (cnt[1:0] == (wp - rp));
    assert (full == (cnt == 3'd4));
    assert (empty == (cnt == 3'd0));

    // same contents as the reference model
    assert (cnt == fv_n);
    if (fv_n > 3'd0) assert (fv_s0 == fv_q0);
    if (fv_n > 3'd1) assert (fv_s1 == fv_q1);
    if (fv_n > 3'd2) assert (fv_s2 == fv_q2);
    if (fv_n > 3'd3) assert (fv_s3 == fv_q3);
    assert (rdata == ((fv_n == 3'd0) ? 8'h00 : fv_q0));
  end

  if (fv_past && rst_n && $past(rst_n)) begin
    if ($past(clr)) assert (cnt == 3'd0);
    else begin
      // F1: no underflow, no overflow
      if ($past(cnt) == 3'd0 && !$past(push)) assert (cnt == 3'd0 && rp == $past(rp));
      if ($past(cnt) == 3'd4 && !$past(pop)) assert (cnt == 3'd4 && wp == $past(wp));
      // the count moves by one at most
      assert (cnt == $past(cnt) || cnt == $past(cnt) + 3'd1 || cnt + 3'd1 == $past(cnt));
    end
  end
end

// Reachability: the FIFO fills, drains, and takes a push while full with a pop.
`ifndef FV_TOP  // too deep to reach through the pins: unit runs only
always @(posedge clk) begin
  if (fv_past && rst_n && $past(rst_n) && !$past(clr)) begin
    cover (cnt == 3'd4);
    cover ($past(cnt) == 3'd1 && cnt == 3'd0);
    cover ($past(cnt) == 3'd4 && $past(push) && $past(pop) && cnt == 3'd4);
  end
end
`endif
