# RP2 firmware: I3C controller and bring-up checklist

Nothing on the Tiny Tapeout demo board speaks I3C, so this folder holds an I3C
SDR controller for the board's RP2 (RP2350 on the current demo board, RP2040 on
older ones, or a bare Raspberry Pi Pico). It is MicroPython, the language the
demo board ships with, so nothing has to be compiled.

Step-by-step instructions for the FPGA dry run are in
[docs/fpga_dry_run.md](../docs/fpga_dry_run.md).

## Files

| File | What it does | Checked how |
| --- | --- | --- |
| `i3cbridge/i3c.py` | I3C frames: START / Sr / STOP, 7E headers, CCCs, ENTDAA, private write and read with End-of-Data and abort, HDR entry, traffic and exit | Against the RTL in simulation |
| `i3cbridge/bridge.py` | The bridge's command protocol: write, read, write-then-read, status, I2C scan | Against the RTL in simulation |
| `i3cbridge/bringup.py` | The bring-up checklist (plan section 15) and the SCL rate sweep | Against the RTL in simulation |
| `i3cbridge/players.py` | Puts the bus on two GPIOs by bit-banging | Not run on hardware yet |
| `i3cbridge/pio_player.py` | Same, with exact timing on a PIO state machine (for the rate sweep) | Experimental, not run on hardware yet |
| `i3cbridge/boards.py` | Reset, `ui_in`, `uo_out` and clock on the demo board (TT SDK) or a bare Pico | Not run on hardware yet |
| `dry_run.py` | Runs the checklist on the demo board | Not run on hardware yet |

"Against the RTL in simulation" means `test/unit/test_firmware.py`: the same
Python files drive the Verilog design in the simulator, with a simulated player in
place of the GPIOs. It runs the whole checklist with and without an I2C sensor
and with the bus cut into the bursts the PIO player uses. Run it with:

```bash
.venv/Scripts/python test/run.py -k firmware
```

So if the checklist fails on hardware, look first at the three files that could
not be simulated (pins, pull-ups, clock, the SDK calls), then at the chip.

## How the code is layered

The bus is described in **slots**. A slot is a quarter of an SCL period: an SCL
level and an SDA state (drive low, drive high, or released). `i3c.py` turns a
frame into a list of slots; a **player** plays the list and returns SDA sampled
in the middle of every slot.

```
bringup.py   checklist                    bridge.py   commands (write / read / status)
        \                                    /
         i3c.py   frames  ->  slots
                     |
   players.BitBangPlayer | pio_player.PioPlayer | the simulator (tests)
```

- `BitBangPlayer` sets the two pins from Python, one slot at a time. SCL comes
  out at roughly 5 to 20 kHz. That is fine: the bridge has no minimum I3C rate,
  only a 35 ms limit on a pause inside a transfer. The RP2's internal pull-up
  on SDA is enough at this speed.
- `PioPlayer` plays up to 32 slots (8 bits) back to back at an exact rate, from
  100 kHz to 1 MHz and above. Use it to find the highest working SCL rate. It
  needs SCL and SDA on consecutive GPIOs (true for `uio[2]` / `uio[3]`) and the
  2.2 kOhm pull-up on SDA.

## Using it from the REPL

On the demo board the SDK's `tt` object already exists:

```python
tt.shuttle.tt_um_i3cbridge.enable()       # the ASIC project, or on the FPGA breakout
                                          # the bitstream /bitstreams/tt_um_i3cbridge.bin
from i3cbridge import boards, players, bringup
from i3cbridge.i3c import I3CController
from i3cbridge.bridge import Bridge

board = boards.TTDemoBoard(tt)            # 25 MHz clock, RP2 drives ui_in and reset
player = players.BitBangPlayer(board.scl_gpio, board.sda_gpio)

bringup.run_all(board, player)            # the whole checklist

# or by hand
i3c = I3CController(player)
i3c.entdaa([0x09])                        # [(pid, bcr, dcr, 0x09, True)]
br = Bridge(i3c, 0x09)
br.status()                               # 0
br.scan()                                 # I2C addresses that answer, e.g. [72]
br.write_read(0x48, 0x00, 2)              # 2 bytes from register 0 of the device at 0x48
```

Rate sweep, once the bit-banged checklist passes:

```python
from i3cbridge.pio_player import PioPlayer
bringup.sweep(lambda hz: PioPlayer(board.scl_gpio, board.sda_gpio, hz), 0x09)
```

## Notes

- The plan (v1.2, section 13) proposed C on the Pico SDK. MicroPython was chosen
  instead: it is what the demo board runs, it works on both the RP2040 and the
  RP2350, and the same source can be simulated against the RTL.
- The demo board SDK gives the RP2 pins a pull-down by default. `TTDemoBoard`
  turns on pull-ups for the downstream I2C lines (`uio[6]`, `uio[7]`) so an empty
  bus idles high; `BitBangPlayer` does the same for I3C SDA.
- A pause longer than 35 ms inside a transfer (for example a long garbage
  collection) makes the bridge give up on that transfer. The commands in
  `bridge.py` are retried by polling, so this shows up as a slower answer, not as
  an error.
