# FPGA dry run

The dry run puts the whole bridge on an FPGA and talks to it with a real I3C
controller: the RP2 firmware in `firmware/`. It is the only test before silicon
that uses real pins, real pull-ups and a controller that was not written as a
simulation model. The plan's exit criterion is: **the dry run completes a
bridged read**.

What is already known before you start:

- The firmware's frames and the whole checklist pass against the RTL in
  simulation (`python test/run.py -k firmware`).
- The design builds for the Tiny Tapeout FPGA breakout (iCE40UP5K): 556 of 5,280
  logic cells, maximum clock 29.7 MHz, so 25 MHz is met.
- Not tried on hardware yet: the pin and board layer of the firmware
  (`players.py`, `pio_player.py`, `boards.py`, `dry_run.py`).

Two set-ups are described. Use A if you have the Tiny Tapeout demo board with the
FPGA breakout, because it is the same RP2, pins and commands as the silicon
bring-up. Use B with any other FPGA board and a Raspberry Pi Pico.

## What you need

| Item | A: TT demo board | B: other FPGA board |
| --- | --- | --- |
| FPGA | TT FPGA breakout (iCE40UP5K "ASIC simulator") on the demo board | Any board with 3.3 V I/O and about 600 free LUTs |
| Controller | The demo board's RP2 (MicroPython SDK v3 already installed) | Raspberry Pi Pico with MicroPython |
| On the PC | Python, `pip install mpremote` | The same, plus the FPGA vendor tools |
| Optional | 3.3 V I2C sensor module at 0x48 (LM75A, TMP102, TMP1075 or similar); 2.2 kOhm resistor; logic analyser | The same |

The checklist passes with nothing on the I2C side. A sensor adds the bridged read
with real data.

## A. Tiny Tapeout demo board with the FPGA breakout

### 1. Get the bitstream

On GitHub open **Actions → fpga → Run workflow** (branch `main`). When it has
finished, download the artifact `fpga_bitstream` and take
`build/tt_um_i3cbridge.bin` from it. The file is about 100 kB.

### 2. Copy the files to the RP2

Connect the demo board by USB.

```bash
mpremote fs mkdir :bitstreams
```

```bash
mpremote fs cp tt_um_i3cbridge.bin :bitstreams/tt_um_i3cbridge.bin
```

```bash
mpremote fs cp -r firmware/i3cbridge :
```

```bash
mpremote reset
```

(`mkdir` reports an error if the folder already exists; that is fine.)

### 3. Run the checklist

```bash
mpremote run firmware/dry_run.py
```

The script loads the bitstream (`tt.shuttle.tt_um_i3cbridge.enable()`), starts
the 25 MHz clock, and runs the checklist with the bit-banged player. Or do the
same by hand in the REPL (`mpremote`), where the SDK's `tt` object already exists:

```python
tt.shuttle.tt_um_i3cbridge.enable()
from i3cbridge import boards, players, bringup
board = boards.TTDemoBoard(tt)
player = players.BitBangPlayer(board.scl_gpio, board.sda_gpio)
report = bringup.run_all(board, player)
```

### 4. Add an I2C sensor (optional)

Plug a 3.3 V sensor module into the bottom-row `uio` Pmod pins: `uio[6]` = SCL,
`uio[7]` = SDA, plus 3V3 and GND. Run the checklist again; step 4 now reads two
bytes from register 0 of the device at 0x48. For another address:

```python
bringup.run_all(board, player, sensor=0x4A)
```

To see what is on the bus:

```python
from i3cbridge.i3c import I3CController
from i3cbridge.bridge import Bridge
br = Bridge(I3CController(player), 0x09)   # after run_all the bridge has address 0x09
[hex(a) for a in br.scan()]
```

### 5. Find the highest SCL rate (optional)

Fit a 2.2 kOhm pull-up from `uio[3]` (I3C SDA) to 3V3, then:

```python
from i3cbridge.pio_player import PioPlayer
bringup.sweep(lambda hz: PioPlayer(board.scl_gpio, board.sda_gpio, hz), 0x09)
```

It prints how many of 20 status round trips worked at each rate from 100 kHz to
2 MHz. The design target is 1 MHz. In simulation every round trip passes up to
1 MHz. The PIO player is experimental: if it stalls or fails at every rate while
the bit-banged checklist passes, the problem is in the player, not in the bridge.

## B. Any FPGA board with a Raspberry Pi Pico

### 1. Build the FPGA project

Add every file in `src/` (the `.v` files) and `fpga/i3cbridge_fpga.v`. The top
module is `i3cbridge_fpga`.

| Port | Connect to |
| --- | --- |
| `clk_board` | The board oscillator. Set parameter `CLK_DIV` to 1 for 25 MHz (or 12 MHz), 2 for 50 MHz, 4 for 100 MHz |
| `rst_n` | A push button (low = reset) or a Pico GPIO |
| `i3c_scl` | Pico GPIO for SCL (input to the FPGA) |
| `i3c_sda` | Pico GPIO for SDA; enable the pad pull-up or fit 2.2 kOhm to 3.3 V |
| `i2c_scl`, `i2c_sda` | The I2C sensor, with pull-ups (pad pull-ups or 4.7 kOhm) |
| `pid_inst[1:0]` | Tie to 0, or two switches |
| `i2c_fast` | Tie to 0 (99.2 kHz) or 1 (367.6 kHz) |
| `status[7:0]` | LEDs or Pico GPIOs: state[3:0], DA_VALID, IRQ, BUSY, ERR |

All pins must be 3.3 V. Constrain the internal clock to 25 MHz (40 ns).

### 2. Wire and run

Connect the Pico's GND to the FPGA board's GND. Use two consecutive GPIOs for SCL
and SDA (needed for the PIO player), for example GP2 and GP3. Copy the firmware
(`mpremote fs cp -r firmware/i3cbridge :`), then in the REPL:

```python
from i3cbridge import boards, players, bringup
board = boards.PicoBoard(scl=2, sda=3, rst_n=4, uo=[6, 7, 8, 9, 10, 11, 12, 13])
player = players.BitBangPlayer(2, 3)
report = bringup.run_all(board, player, inst=0)
```

`inst` is the value strapped on `pid_inst`. Leave out `rst_n` to be asked to
press the reset button, and `uo` if the status pins are not wired (those checks
are then skipped).

## What a pass looks like

This is the transcript from simulation with a sensor at 0x48 whose register 0
reads `19 80`. On hardware the data bytes differ; everything else should match.

```
== 1. Reset state
[PASS] after reset every status output is low - uo_out = 0x00
[PASS] I3C SDA is released and pulled high - if this fails, check the SDA pull-up

== 2. Dynamic address assignment
[PASS] ENTDAA finds one target and it ACKs the address - 1 found
       PID 0xFFFE00012000  BCR 0x01  DCR 0x00  DA 0x09
[PASS] PID: manufacturer 0x7FFF, fixed type, part 0x0001
[PASS] PID instance matches ui_in[2:1] - instance 2
[PASS] BCR = 0x01, DCR = 0x00
[PASS] DA_VALID is high - uo_out = 0x10
[PASS] a target that has an address does not answer ENTDAA
[PASS] RSTDAA is ACKed
[PASS] DA_VALID is low after RSTDAA - uo_out = 0x00
[PASS] the old address is not answered any more
[PASS] SETDASA is NACKed (not supported)
[PASS] ENTDAA works again after RSTDAA
[PASS] DA_VALID is high again - uo_out = 0x10

== 3. Status command (nothing needed on the I2C side)
[PASS] status round trip returns 0x00 - 0x00 (ok, FIFO count 0)
[PASS] the 7E-prefixed form of private transfers works

== 4. Downstream I2C (device at 0x48 if present)
[PASS] bridged read of 2 bytes from register 0 - data 19 80
       as a 16-bit temperature register (LM75 / TMP102 style): 25.50 C
[PASS] ERR is low after a good transfer - uo_out = 0x10
[PASS] bridged write is acknowledged - 0x00 (ok, FIFO count 0)
[PASS] plain read returns the same register - data 19 80

== 5. HDR entry and exit
[PASS] ENTHDR0 puts the target in HDR (state 8) - uo_out = 0x18
[PASS] it stays there through 200 edges of HDR traffic - uo_out = 0x18
[PASS] the exit pattern returns it to IDLE with its address - uo_out = 0x10
[PASS] the bridge still answers - 0x00 (ok, FIFO count 0)

== 6. Parity error and aborted read
[PASS] the write with a bad T-bit was ACKed at the address
[PASS] ERR is high and the target is back in IDLE - uo_out = 0x90
[PASS] status shows the parity error - 0x40 (PARITY, FIFO count 0)
[PASS] next command accepted
[PASS] read aborted by the controller after 1 byte
[PASS] the rest of the response is dropped (IRQ low, IDLE) - uo_out = 0x10
[PASS] a new command clears the parity flag - 0x00 (ok, FIFO count 0)
[PASS] the downstream NACK flag matches step 4 - 0x00 (ok, FIFO count 0)

32 checks, 0 failed
```

Without a sensor step 4 reads:

```
== 4. Downstream I2C (device at 0x48 if present)
       no device answered at 0x48: checking the NACK path instead
[PASS] a NACKed read is padded with zeros and sets the NACK flag - data 00 00, status 0x80 (NACK, FIFO count 0)
[PASS] ERR is high - uo_out = 0x90
[PASS] a NACKed write reports NACK and the unsent byte - 0x81 (NACK, FIFO count 1)
```

and the run ends with `31 checks, 0 failed`.

## If something fails

| Symptom | Likely cause |
| --- | --- |
| "I3C SDA is released and pulled high" fails | No pull-up on SDA, SCL and SDA swapped, or the wrong GPIO numbers |
| ENTDAA finds 0 targets | No clock (on the demo board check `tt.auto_clocking_freq`), reset held low, bitstream not loaded, or SCL / SDA not reaching `uio[2]` / `uio[3]` |
| ENTDAA works once but "works again after RSTDAA" fails | Watch `uo_out`: DA_VALID (bit 4) must drop after RSTDAA |
| Status shows TIMEOUT (0x10) with nothing on the I2C bus | The I2C lines are low: no pull-ups on `uio[6]` / `uio[7]`. The bridge waits for SCL to rise and gives up after 35 ms |
| Status shows NACK (0x80) | No I2C device at that address. Expected without a sensor |
| Random failures on the FPGA only | Timing: try a 12.5 MHz clock, `boards.TTDemoBoard(tt, clock_hz=12_500_000)`. The I2C rates halve and the timeout doubles |
| `BridgeError: bridge never ACKed the private read` | The I2C transfer never finished and the timeout did not fire either: check the clock frequency |
| `uo_out` checks fail but the data checks pass | The `uo` GPIO list is wired in a different order (set-up B) |

## What to keep for the report

- The full transcript, with and without a sensor.
- The clock frequency used and the FPGA tool's maximum frequency.
- The result of the rate sweep, if run.
- A logic-analyser capture of one ENTDAA and one bridged read, if a logic
  analyser is available (channels: I3C SCL, I3C SDA, I2C SCL, I2C SDA, IRQ).
- Anything that had to be changed in `players.py`, `boards.py` or `dry_run.py`
  to make it run, so the files can be corrected.
