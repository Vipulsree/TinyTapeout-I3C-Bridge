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
| 2 | 20-bit timeout module (`timeout20`), wired in with `cmd_ctrl` | Module done |
| 3 | `i3c_bus_cond` (done early), `cmd_ctrl`; push to GitHub, skeleton hardened | Next |
| 4–5 | `i3c_tgt` private write/read (M3), `i2c_ctrl` (M4), RP2040 firmware starts | To do |
| 6 | `i3c_daa`: ENTDAA, SETDASA, RSTDAA (M3) | To do |

Test results today: 29/29 passing (top 4, i3c_bus_cond 6, fifo4x8 5, clkdiv 3,
timeout20 5, sync2_edge 3, I²C model 3).

## Layout

```
src/        project.v (tt_um_i3cbridge), i3c_bus_cond.v, sync2_edge.v, fifo4x8.v, clkdiv.v, timeout20.v
test/       tb.v + test.py (top level, run by the TT CI through make)
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
- Confirm the PID placeholder, part ID and static address (docs/architecture.md).
- Enable GitHub Pages for the `gds` viewer job ([TT FAQ](https://tinytapeout.com/faq/#my-github-action-is-failing-on-the-pages-part)).

## Tiny Tapeout resources

- [FAQ](https://tinytapeout.com/faq/) · [Recommended pinouts](https://tinytapeout.com/specs/pinouts/) · [Local hardening](https://www.tinytapeout.com/guides/local-hardening/)
