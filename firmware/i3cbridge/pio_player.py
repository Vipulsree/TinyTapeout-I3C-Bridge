# SPDX-License-Identifier: Apache-2.0
"""Slot player with exact timing, on one PIO state machine (MicroPython, RP2040 / RP2350).

EXPERIMENTAL: the slot lists it plays and the way it cuts them into bursts are
checked in simulation, but this PIO program has not run on hardware yet. Bring
the bridge up with players.BitBangPlayer first; use this one for the SCL rate
sweep (bringup.sweep).

One slot is four state-machine cycles: SCL and the SDA value change together,
the SDA direction one cycle later (so releasing or taking the line never glitches),
and SDA is sampled half way through. Eight slots travel in one FIFO word, so up
to 32 slots (8 bits) play back to back at the programmed rate; between bursts the
bus waits where the last slot left it, and bursts are cut at a point with SCL low.

SCL must be on GPIO n and SDA on GPIO n + 1 (true for uio[2] / uio[3] on the demo
board). Fit a 2.2 kOhm pull-up on SDA for rates above about 100 kHz.
"""
import rp2
from machine import Pin
from time import sleep_us, ticks_diff, ticks_ms

from .i3c import Z, split_bursts


@rp2.asm_pio(out_init=(rp2.PIO.OUT_HIGH, rp2.PIO.IN_HIGH), out_shiftdir=rp2.PIO.SHIFT_RIGHT, autopull=True,
             pull_thresh=32, in_shiftdir=rp2.PIO.SHIFT_LEFT, autopush=True, push_thresh=8)
def _slot_player():
    out(pins, 2)        # SCL level, SDA value
    out(pindirs, 2)     # SCL always driven, SDA driven or released
    in_(pins, 1)[1]     # sample SDA; one more cycle makes it four per slot


class PioPlayer:
    def __init__(self, scl, sda, scl_hz=100_000, sm_id=4):
        """sm_id 4 is the first state machine of PIO1; the demo board SDK uses PIO0."""
        if sda != scl + 1:
            raise ValueError("SDA must be the GPIO after SCL")
        Pin(sda, Pin.IN, Pin.PULL_UP)
        self.sm = rp2.StateMachine(sm_id, _slot_player, freq=16 * scl_hz, out_base=Pin(scl), in_base=Pin(sda))
        self.sm.active(1)
        self._val = 1  # value latched on the SDA output, kept while released

    def _nibble(self, s):
        sda = s & 3
        if sda == Z:
            return (s >> 2) | (self._val << 1) | 0b0100
        self._val = sda
        return (s >> 2) | (sda << 1) | 0b1100

    def run(self, slots):
        out = bytearray(len(slots))
        n = 0
        for burst in split_bursts(slots, 32):
            words = (len(burst) + 7) // 8
            self.sm.active(0)  # load the whole burst (4 words fill the FIFO), then let it run
            for w in range(words):
                word = 0
                for i in range(8):
                    k = min(w * 8 + i, len(burst) - 1)  # short word: hold the last slot
                    word |= self._nibble(burst[k]) << (4 * i)
                self.sm.put(word)
            self.sm.active(1)
            for w in range(words):
                t0 = ticks_ms()
                while not self.sm.rx_fifo():
                    if ticks_diff(ticks_ms(), t0) > 500:
                        raise OSError("PIO player stalled")
                byte = self.sm.get() & 0xFF
                for i in range(8):
                    if w * 8 + i < len(burst):
                        out[n] = (byte >> (7 - i)) & 1
                        n += 1
        return out

    def wait_us(self, us):
        sleep_us(us)

    def close(self):
        self.sm.active(0)
