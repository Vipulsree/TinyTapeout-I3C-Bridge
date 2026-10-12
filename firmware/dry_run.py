# SPDX-License-Identifier: Apache-2.0
"""Run the bring-up checklist on the Tiny Tapeout demo board.

Copy the i3cbridge folder to the board first, then run this file on it:

    mpremote fs cp -r firmware/i3cbridge :
    mpremote run firmware/dry_run.py

PROJECT is the name of the design in tt.shuttle: the top-module name on the ASIC,
the bitstream file name without ".bin" on the FPGA breakout (the CI's fpga job
names the bitstream after the top module, so both are the same).
"""
from ttboard.boot.demoboard_detect import DemoboardDetect
from ttboard.demoboard import DemoBoard

from i3cbridge import bringup
from i3cbridge.boards import TTDemoBoard
from i3cbridge.players import BitBangPlayer

PROJECT = "tt_um_i3cbridge"
DA = 0x09               # dynamic address to assign
SENSOR = 0x48           # downstream I2C device to try (the checklist also passes without one)

DemoboardDetect.probe()
tt = DemoBoard.get()
getattr(tt.shuttle, PROJECT).enable()

board = TTDemoBoard(tt)
player = BitBangPlayer(board.scl_gpio, board.sda_gpio)
report = bringup.run_all(board, player, da=DA, sensor=SENSOR)
print("DRY RUN PASSED" if not report.failed else "DRY RUN FAILED: %d check(s)" % len(report.failed))
