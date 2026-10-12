![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Track B — Minimal I3C target → I²C bridge

One Tiny Tapeout tile (sky130A, 25 MHz) that joins an I3C bus as an SDR target
and runs I²C transactions on a downstream bus through private writes and reads.
Course: EC373TA VLSI Physical Design. Track A (the multi-mode UART / SPI / I²C bridge) lives in its own repo.

- Datasheet: [docs/info.md](docs/info.md)
- FSM, SDA driver, identity and model API: [docs/architecture.md](docs/architecture.md)
- Formal proofs of F1–F5: [formal/README.md](formal/README.md)
- RP2 I3C controller firmware: [firmware/README.md](firmware/README.md)
- FPGA dry run, step by step: [docs/fpga_dry_run.md](docs/fpga_dry_run.md)
- Full plan: `Track_B_I3C_Bridge_Plan.pdf` (team folder)

## Status

| Week | Milestone | State |
| --- | --- | --- |
| 1 | Repo, I3C subset + identity frozen, test setup, I²C bus models | Done |
| 2 | Python I3C controller model; `sync2_edge`, `clkdiv`, `fifo4x8` | Done |
| 2 | 20-bit timeout module (`timeout20`) | Done |
| 3 | `i3c_bus_cond`, `cmd_ctrl` with the timeout wired in; push to GitHub, skeleton hardened | Done (26–27 Sep) |
| 4–5 | `i3c_tgt` private write/read (M3), `i2c_ctrl` (M4) | Done early (27 Sep) |
| 4–7 | RP2 I3C controller firmware (M3) | Done (12 Oct): MicroPython, checked against the RTL in simulation; not yet run on hardware |
| 6 | `i3c_daa`: ENTDAA, RSTDAA (M3); SETDASA later removed for area | Done early (27 Sep) |
| 7–8 | Full RTL hardened (area, timing); DAA, HDR, error tests | Done: 1x1 tile, timing and DRC/LVS clean, gate-level pass |
| 8 | Formal properties F1–F5 | Done (12 Oct): all five proved, CI job `formal` |
| 9 | FPGA dry run with the RP2 firmware | Files ready ([docs/fpga_dry_run.md](docs/fpga_dry_run.md)); to be run on hardware |
| 10–12 | Gate-level sim, sign-off, datasheet, submit | Gate-level sim and sign-off pass in CI; submission to do |

Test results today: 64/64 passing (top level 17, cmd_ctrl 8, i2c_ctrl 7,
two bridges 2, i3c_bus_cond 6, fifo4x8 5, clkdiv 3, timeout20 5, sync2_edge 3,
I²C model 3, firmware 5). The top level covers ENTDAA / RSTDAA (SETDASA NACKed),
every bridged operation, NACK while busy, End-of-Data and controller abort,
TE1–TE3, HDR entry and exit, downstream NACK and both timeouts; the two-bridge
suite checks ENTDAA arbitration on a shared bus; `i2c_ctrl` measures the
downstream START / STOP timing against UM10204; the firmware suite runs the RP2
code and its bring-up checklist against the RTL.

## Layout

```
src/        project.v (tt_um_i3cbridge), i3c_tgt.v, i3c_daa.v, i3c_bus_cond.v, cmd_ctrl.v, i2c_ctrl.v,
            sync2_edge.v, fifo4x8.v, clkdiv.v, timeout20.v
test/       tb.v + test.py (top level, run by the TT CI through make, RTL and gate level)
test/unit/  unit tests per module + the I²C model check
test/models i3c_controller.py (I3C SDR controller), I²C target and controller models
test/run.py runs everything without make (Windows friendly)
formal/     SymbiYosys proofs of F1–F5 (run.py, one .sby and one _props.vh per module)
firmware/   MicroPython I3C controller and bring-up checklist for the demo board's RP2
fpga/       wrapper to put the design on any FPGA board
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

Formal proofs (about a minute):

```bash
.venv/Scripts/pip install -r formal/requirements.txt
.venv/Scripts/python formal/run.py
```

## Before submission

- Run the FPGA dry run ([docs/fpga_dry_run.md](docs/fpga_dry_run.md)) and keep its transcript.
- Check the `author` line in `info.yaml`: every author, then the guide and the college.
- The top module stays `tt_um_i3cbridge`: no other project on the shuttle uses the name, and a
  rename would mean hardening again.
- Confirm the PID placeholder and part ID (`src/i3c_daa.v`, docs/architecture.md).
- Import the repository into the department's GitHub account, set its description and
  Pages source there, and submit that URL to the shuttle.

## Tiny Tapeout resources

- [FAQ](https://tinytapeout.com/faq/) · [Recommended pinouts](https://tinytapeout.com/specs/pinouts/) · [Local hardening](https://www.tinytapeout.com/guides/local-hardening/)
