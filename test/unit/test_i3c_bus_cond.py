# SPDX-License-Identifier: Apache-2.0
"""Unit tests for i3c_bus_cond, driven by the I3C controller model through the
synchroniser. Also exercises the model's START/Sr/STOP, SDR bytes and HDR exit."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

from models.i3c_controller import BROADCAST, I3CController, odd_parity


class Counts:
    def __init__(self, dut):
        self.dut = dut
        self.start = self.stop = self.exit = 0

    async def run(self):
        while True:
            await FallingEdge(self.dut.clk)
            self.start += int(self.dut.start.value)
            self.stop += int(self.dut.stop.value)
            self.exit += int(self.dut.hdr_exit.value)

    def get(self):
        return self.start, self.stop, self.exit


async def setup(dut, period_ns=1000):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    ctl = I3CController(dut.i3c_scl_drv, dut.i3c_sda_oe, dut.i3c_sda_out, dut.i3c_sda, period_ns)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    counts = Counts(dut)
    cocotb.start_soon(counts.run())
    return ctl, counts


async def settle(dut):
    await ClockCycles(dut.clk, 6)


@cocotb.test()
async def test_odd_parity_helper(dut):
    assert odd_parity(0x00, 8) == 1 and odd_parity(0xFF, 8) == 1
    assert odd_parity(0x01, 8) == 0 and odd_parity(0x81, 8) == 1
    assert odd_parity(0x7E, 7) == 1 and odd_parity(0x08, 7) == 0


@cocotb.test()
async def test_start_and_stop(dut):
    ctl, counts = await setup(dut)
    await ctl.private_write(0x08, [0x12, 0x34])  # nobody ACKs: S, header, P
    await settle(dut)
    assert counts.get() == (1, 1, 0)


@cocotb.test()
async def test_repeated_start(dut):
    ctl, counts = await setup(dut)
    await ctl.private_write(0x08, [], use_7e=True)  # S, 7E/W, Sr, DA/W, P
    await settle(dut)
    assert counts.get() == (2, 1, 0)


@cocotb.test()
async def test_sdr_bytes_never_look_like_hdr_exit(dut):
    ctl, counts = await setup(dut)
    rng = random.Random(1)
    data = [0x00, 0xFF, 0x55, 0xAA] + [rng.getrandbits(8) for _ in range(28)]
    await ctl.start()
    await ctl.header(BROADCAST, 0)
    for b in data:
        await ctl.write_byte(b)
    await ctl.stop()
    await settle(dut)
    assert counts.get() == (1, 1, 0)


@cocotb.test()
async def test_hdr_exit_detected_once(dut):
    ctl, counts = await setup(dut)
    await ctl.enthdr(0)
    await ctl.hdr_traffic(300, random.Random(2))  # includes fake START/STOP
    await settle(dut)
    assert counts.exit == 0, "HDR traffic was mistaken for the exit pattern"
    stops_before = counts.stop
    await ctl.hdr_exit()
    await settle(dut)
    assert counts.exit == 1
    assert counts.stop == stops_before + 1  # the STOP that follows the exit pattern


@cocotb.test()
async def test_three_pulses_is_not_an_exit(dut):
    ctl, counts = await setup(dut)
    await ctl.enthdr(0)
    await ctl.hdr_exit(pulses=3, then_stop=False)
    await settle(dut)
    assert counts.exit == 0
    await ctl.hdr_exit(pulses=4)
    await settle(dut)
    assert counts.exit == 1
