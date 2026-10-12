# SPDX-License-Identifier: Apache-2.0
"""Slot player that bit-bangs the I3C bus with two GPIOs (MicroPython, any RP2).

This is the player to start with: it needs no PIO and no exact timing. SCL comes
out at a few kHz to a few tens of kHz, which the bridge accepts (its only limits
are SCL <= 1 MHz and no pause longer than 35 ms inside a transfer).

SDA uses the RP2's internal pull-up, which is enough at these rates. For the fast
player (pio_player.py) fit the 2.2 kOhm pull-up from the plan.
"""
from machine import Pin
from time import sleep_us

from .i3c import Z


class BitBangPlayer:
    def __init__(self, scl, sda, quarter_us=20):
        """scl, sda: GPIO numbers. quarter_us: length of one slot (a quarter SCL period)."""
        self.scl = Pin(scl, Pin.OUT, value=1)
        self.sda = Pin(sda, Pin.IN, Pin.PULL_UP)
        self._scl = 1
        self._sda = Z
        self.half = max(1, quarter_us // 2)

    def _set_sda(self, state):
        if state != self._sda:
            if state == Z:
                self.sda.init(Pin.IN, Pin.PULL_UP)
            else:
                self.sda.init(Pin.OUT, value=state)
            self._sda = state

    def run(self, slots):
        out = bytearray(len(slots))
        i = 0
        for s in slots:
            scl = s >> 2
            if scl < self._scl:  # falling SCL: move SCL first, then SDA
                self.scl.value(0)
                self._set_sda(s & 3)
            else:                # SDA first, then a rising SCL
                self._set_sda(s & 3)
                if scl != self._scl:
                    self.scl.value(1)
            self._scl = scl
            sleep_us(self.half)
            out[i] = self.sda.value()
            sleep_us(self.half)
            i += 1
        return out

    def wait_us(self, us):
        sleep_us(us)
