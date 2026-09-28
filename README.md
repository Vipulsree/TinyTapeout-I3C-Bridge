![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Track B — Minimal I3C target → I²C bridge

One Tiny Tapeout tile (sky130A, 25 MHz) that joins an I3C bus as an SDR target
and runs I²C transactions on a downstream bus through private writes and reads.
Course: EC373TA VLSI Physical Design. Track A (the six-mode bridge) lives in its own repo.

- Datasheet: [docs/info.md](docs/info.md)
- FSM, SDA driver, identity and model API: [docs/architecture.md](docs/architecture.md)
- Full plan: `Track_B_I3C_Bridge_Plan.pdf` (team folder)

## Status

| Week | Milestone | State |
| --- | --- | --- |
| 1 | Repo, I3C subset + identity frozen, test setup, I²C bus models | Done |
| 2 | Python I3C controller model; `sync2_edge`, `clkdiv`, `fifo4x8` | Done |
| 2 | 20-bit timeout module (`timeout20`) | Done |
| 3 | `i3c_bus_cond`, `cmd_ctrl` with the timeout wired in; push to GitHub, skeleton hardened | Done (26–27 Sep) |
| 4–5 | `i3c_tgt` private write/read (M3), `i2c_ctrl` (M4) | Done early (27 Sep) |
| 4–7 | RP2040 I3C controller firmware (M3) | To do |
| 6 | `i3c_daa`: ENTDAA, RSTDAA (M3); SETDASA later removed for area | Done early (27 Sep) |
| 7–8 | Full RTL hardened (area, timing); DAA, HDR, error tests | Done: 1x1 tile, timing and DRC/LVS clean, gate-level pass |
| 8–9 | Formal properties F1–F5, FPGA dry run with the RP2040 | To do |
| 10–12 | Gate-level sim, sign-off, datasheet, submit | To do |

Test results today: 58/58 passing (top level 17, cmd_ctrl 8, i2c_ctrl 6,
two bridges 2, i3c_bus_cond 6, fifo4x8 5, clkdiv 3, timeout20 5, sync2_edge 3,
I²C model 3). The top level covers ENTDAA / RSTDAA (SETDASA NACKed), every bridged
operation, NACK while busy, End-of-Data and controller abort, TE1–TE3, HDR entry
and exit, downstream NACK and both timeouts; the two-bridge suite checks ENTDAA
arbitration on a shared bus.

## Layout

```
src/        project.v (tt_um_i3cbridge), i3c_tgt.v, i3c_daa.v, i3c_bus_cond.v, cmd_ctrl.v, i2c_ctrl.v,
            sync2_edge.v, fifo4x8.v, clkdiv.v, timeout20.v
test/       tb.v + test.py (top level, run by the TT CI through make, RTL and gate level)
test/unit/  unit tests per module + the I²C model check
test/models i3c_controller.py (I3C SDR controller), I²C target and controller models
test/run.py runs everything without make (Windows friendly)
```

## Running the tests

Needs Icarus Verilog 12 and Python 3.11+.

```bash
python -m venv .venv
.venv/Scripts/pip install -r test/requirements.txt   # Linux/macOS: .venv/bin/pip
.venv/Scripts/python test/run.py                     # everything
.venv/Scripts/python test/run.py -k i3c              # I3C suites only
```

On Linux the TT flow also works: `cd test && make`.

## Before submission

- Put all four team members in `info.yaml` (`author`).
- Consider renaming the top module to `tt_um_<github user>_i3cbridge` so it is unique on the shuttle.
- Confirm the PID placeholder and part ID (`src/i3c_daa.v`, docs/architecture.md).

## Tiny Tapeout resources

- [FAQ](https://tinytapeout.com/faq/) · [Recommended pinouts](https://tinytapeout.com/specs/pinouts/) · [Local hardening](https://www.tinytapeout.com/guides/local-hardening/)
