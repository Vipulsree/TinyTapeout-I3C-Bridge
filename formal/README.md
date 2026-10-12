# Formal proofs (SymbiYosys)

Properties F1 to F5 of the plan, proved for every reachable state, not only for
the cases a test happens to drive.

```bash
pip install -r formal/requirements.txt     # once: Yosys + SymbiYosys (YoWASP) and Z3
python formal/run.py                       # every proof, about a minute
python formal/run.py --selftest            # break the RTL on purpose: every proof must fail
```

With the OSS CAD Suite installed (`sby`, `yosys` and `z3` on the PATH) the same
script uses those tools instead. Work files go to `formal/build/`.

## What is proved

| Property | Statement | Where |
| --- | --- | --- |
| F1 | The FIFO count stays in 0..4: a push while full is dropped, a pop while empty is ignored. The FIFO also matches a reference queue, so bytes come out in order and an empty FIFO reads 0x00. | `fifo4x8_props.vh` |
| F2 | The I3C SDA pad output is high only inside a private read (state 7). In the open-drain phases (ACK, ENTDAA identity) the pad can only pull low. The target drives SDA in those three states only. | `i3c_tgt_props.vh`, `project_props.vh` |
| F3 | The SDA drive changes only in the clock cycle after SCL fell. Two exceptions, both of which only release the line: the End-of-Data hand-off as SCL rises in a read T-bit, and START / STOP / bus stall. | `i3c_tgt_props.vh`, `project_props.vh` |
| F4 | One cycle after STOP or a bus-stall timeout the target is in IDLE with SDA released (HDR leaves only through the exit pattern). The timer never lets a wait last more than `limit` idle cycles, and its expiry in EXEC moves the controller to RESPOND with the timeout flag and aborts the I2C transfer. | `i3c_tgt_props.vh`, `timeout20_props.vh`, `cmd_ctrl_props.vh` |
| F5 | `uio_oe[2]` is always 0: the target never drives I3C SCL. Unused pads are never driven and the I2C pads never drive high. | `project_props.vh` |

`i2c_ctrl_props.vh` adds basic safety for the downstream controller (legal
states, lines released when idle, an abort always ends in STOP without `d_done`).

Every `.sby` file has two tasks. `prove` is an unbounded proof by k-induction.
`cover` asks the solver for traces that reach the interesting states (push-pull
drive, End-of-Data hand-off, HDR, timeout), which shows the properties are not
true only because nothing happens.

`project.sby` proves the pin-level properties on the whole design and re-checks
every module's properties in place. There the assumptions made for a module on
its own (for example "SCL never rises and falls in the same cycle") are asserted
instead of assumed.

## How the properties are attached

Each checked module ends with

```verilog
`ifdef FORMAL
  `include "<module>_props.vh"
`endif
```

`read_verilog -formal` defines `FORMAL`; simulation, lint and the hardening flow
do not, so the RTL they see is unchanged. (Yosys 0.69 accepts `bind` but ignores
it, which is why the properties are included rather than bound.)

## Self-test

`python formal/run.py --selftest` copies the sources, makes one deliberate
mistake per property (a FIFO that accepts a fifth byte, an ACK driven high, an
SDA change on a rising SCL, a STOP that does not return to IDLE, a timer that
misses its limit, a timeout that does not end EXEC, a target that drives SCL) and
checks that the matching proof no longer passes. `FAIL` means the solver found a
counter-example from reset; `UNKNOWN` means the induction step failed first.

## Limits

- The proofs are about the RTL, with ideal synchronous inputs. Pad delays and
  metastability are covered by the two-flop synchronisers and STA, not here.
- F4 at system level relies on the module proofs: the timer is proved for any
  limit, and `cmd_ctrl` and `i3c_tgt` are proved to act on its pulse. A single
  trace of 875,000 cycles is not unrolled.
- A complete ENTDAA or a complete I2C transaction is too long for a quick cover
  run; those sequences are exercised by the cocotb suite.
