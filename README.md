![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Minimal I3C target to I2C bridge

- [Read the documentation for project](docs/info.md)

A Tiny Tapeout project (one 1x1 tile, sky130A, 25 MHz) that joins an I3C bus as an SDR
target and runs I2C transactions on a downstream I2C bus. An I3C controller gives the
bridge a dynamic address with ENTDAA, sends each request as a private write and collects
the result with a private read.

## How it works

- `i3c_tgt`, `i3c_daa`, `i3c_bus_cond`: the I3C Basic SDR target. Address match, ENTDAA and
  RSTDAA, T-bit parity, End-of-Data, HDR entry and exit.
- `cmd_ctrl`: reads the 2-byte header (command, I2C address) and up to 4 payload bytes into
  a FIFO, runs the request, then returns the data or one status byte.
- `i2c_ctrl`: the downstream I2C controller at 99.2 kHz or 367.6 kHz, with clock stretching.
  A 35 ms timeout aborts a transfer that stalls.

Pinout, command format and status bits are in [docs/info.md](docs/info.md); design notes
are in [docs/architecture.md](docs/architecture.md).

## How to test

On the demo board the RP2 is the I3C controller: copy `firmware/i3cbridge` to it and run
the bring-up checklist ([firmware/README.md](firmware/README.md)).

In simulation (Icarus Verilog 12, Python 3.11+):

```bash
pip install -r test/requirements.txt
cd test && make -B                 # the Tiny Tapeout cocotb testbench
```

```bash
python test/run.py                 # every suite, unit tests included (also works on Windows)
pip install -r formal/requirements.txt
python formal/run.py               # formal proofs
```

## Repository layout

| Folder | Contents |
| --- | --- |
| `src/` | Verilog sources, top module `tt_um_i3cbridge` in `project.v` |
| `test/` | cocotb testbench (`tb.v`, `test.py`), unit tests and bus models |
| `formal/` | SymbiYosys proofs ([formal/README.md](formal/README.md)) |
| `firmware/` | MicroPython I3C controller and bring-up checklist for the RP2 |
| `fpga/` | Wrapper for running the design on an FPGA ([docs/fpga_dry_run.md](docs/fpga_dry_run.md)) |

## What is Tiny Tapeout?

Tiny Tapeout is an educational project that aims to make it easier and cheaper than ever to get your digital and analog designs manufactured on a real chip.

To learn more and get started, visit https://tinytapeout.com.

## Resources

- [FAQ](https://tinytapeout.com/faq/)
- [Digital design lessons](https://tinytapeout.com/digital_design/)
- [Learn how semiconductors work](https://tinytapeout.com/siliwiz/)
- [Join the community](https://tinytapeout.com/discord)
- [Build your design locally](https://www.tinytapeout.com/guides/local-hardening/)
