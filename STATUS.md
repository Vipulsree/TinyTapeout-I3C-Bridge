# Project status

Team tracking notes. The design itself is described in [README.md](README.md) and
[docs/info.md](docs/info.md). Last updated 16 Nov 2026.

## Shuttle

| Item | Value |
| --- | --- |
| Shuttle | Tiny Tapeout SKY26e (sky130A); SKY26d was missed |
| Closes | 30 Nov 2026 ([tinytapeout.com/runs](https://tinytapeout.com/runs)) |
| Chips expected | about 25 May 2027, shipping about 25 Jun 2027 |
| Tile | 1x1, bought with the department's GitHub account (RVCE-ECE); the Tiny Tapeout project points at the placeholder repo `RVCE-ECE/I3C_I2C_bridge` |
| Workflows | `tt-gds-action@ttsky26e` (the same action commit as `ttsky26d`) |
| Top module | `tt_um_i3cbridge`; no other SKY26e project uses it (28 projects checked on 16 Nov 2026). A rename means hardening again |

## Milestones

| Week | Milestone | State |
| --- | --- | --- |
| 1 | Repo, I3C subset + identity frozen, test setup, I2C bus models | Done |
| 2 | Python I3C controller model; `sync2_edge`, `clkdiv`, `fifo4x8` | Done |
| 2 | 20-bit timeout module (`timeout20`) | Done |
| 3 | `i3c_bus_cond`, `cmd_ctrl` with the timeout wired in; push to GitHub, skeleton hardened | Done (26-27 Sep) |
| 4-5 | `i3c_tgt` private write/read, `i2c_ctrl` | Done early (27 Sep) |
| 4-7 | RP2 I3C controller firmware | Done (12 Oct): MicroPython, checked against the RTL in simulation; not yet run on hardware |
| 6 | `i3c_daa`: ENTDAA, RSTDAA; SETDASA later removed for area | Done early (27 Sep) |
| 7-8 | Full RTL hardened (area, timing); DAA, HDR, error tests | Done: 1x1 tile, timing and DRC/LVS clean, gate-level pass |
| 8 | Formal properties F1-F5 | Done (12 Oct): all five proved, CI job `formal` |
| 9 | FPGA dry run with the RP2 firmware | Files ready ([docs/fpga_dry_run.md](docs/fpga_dry_run.md)); to be run on hardware |
| 10-12 | Gate-level sim, sign-off, datasheet, submit | Gate-level sim and sign-off pass in CI; submission to do |

## Blocks

| Module | Owner | Status |
| --- | --- | --- |
| `sync2_edge` | M4 | Done, unit-tested |
| `i3c_bus_cond` | M3 | Done, unit-tested |
| `fifo4x8` | M4 | Done, unit-tested |
| `clkdiv` | M4 | Done, unit-tested |
| `timeout20` | M4 | Done, unit-tested |
| `cmd_ctrl` | M4 | Done, unit-tested |
| `i2c_ctrl` | M4 | Done, unit-tested |
| `i3c_tgt` | M3 | Done, top-level tests |
| `i3c_daa` | M3 | Done, top-level + two-bridge tests |
| `project.v` | M3 | Done |

## Tests

64/64 passing (top level 17, cmd_ctrl 8, i2c_ctrl 7, two bridges 2, i3c_bus_cond 6,
fifo4x8 5, clkdiv 3, timeout20 5, sync2_edge 3, I2C model 3, firmware 5). The top level
covers ENTDAA / RSTDAA (SETDASA NACKed), every bridged operation, NACK while busy,
End-of-Data and controller abort, TE1-TE3, HDR entry and exit, downstream NACK and both
timeouts; the two-bridge suite checks ENTDAA arbitration on a shared bus; `i2c_ctrl`
measures the downstream START / STOP timing against UM10204; the firmware suite runs the
RP2 code and its bring-up checklist against the RTL. Sign-off numbers are in
[docs/architecture.md](docs/architecture.md#area-and-sign-off).

## Before submission

- [ ] Run the FPGA dry run on hardware ([docs/fpga_dry_run.md](docs/fpga_dry_run.md)) and keep its transcript.
- [ ] Confirm the PID placeholder and part ID (`src/i3c_daa.v`, [docs/architecture.md](docs/architecture.md)).
- [ ] Check every frame against the MIPI I3C Basic v1.2 specification.
- [ ] Import this repo into the RVCE-ECE account. The placeholder repo already holds the name
      `I3C_I2C_bridge`: rename or delete it first, or import under another name.
- [ ] In the imported repo: set Settings > Pages > Source to GitHub Actions, and set the About
      description to:

      > This project was executed by Shridatta M Hebbar, Vipul S, Shreevathsa Kuthethoor, Anay Katti and
      > Shylashree N from RVCE. We sincerely acknowledge CoE-ICAS and the Dept. of ECE, RVCE, for the
      > resources. Our special gratitude goes to Dr. H V Ravish Aradhya (HoD, ECE), Dr. K S Geetha
      > (Vice Principal) and Dr. K N Subramanya (Principal)
- [ ] One commit after those changes; `test`, `gds` and `docs` all green; the repo shows Public.
- [ ] In the Tiny Tapeout app, change the project's repo link to the imported repo and click
      "Submit a new revision" once.
- [ ] Check that the project appears in
      [tinytapeout-sky-26e](https://github.com/TinyTapeout/tinytapeout-sky-26e) and passes its precheck.
