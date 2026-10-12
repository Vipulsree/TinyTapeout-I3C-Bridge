# SPDX-License-Identifier: Apache-2.0
"""The RP2 firmware (firmware/i3cbridge) against the RTL.

The firmware's I3C controller, bridge client and bring-up checklist are plain
blocking Python. Here they run unchanged in a thread next to the simulator: the
slot player below puts each slot on the testbench's I3C pins instead of on GPIOs.
So the frames and the checklist that will run on the demo board are the ones
exercised here, with and without an I2C sensor, back to back and cut into the
bursts the PIO player uses."""
import cocotb
from cocotb.clock import Clock
from cocotb.task import bridge, resume
from cocotb.triggers import ClockCycles, FallingEdge, Timer

from i3cbridge import bringup
from i3cbridge.bridge import NACK, Bridge
from i3cbridge.i3c import I3CController, Z, split_bursts
from models.i2c_target import I2CTarget

CLK_NS = 40  # 25 MHz
SENSOR = 0x48
DA = 0x09


class SimPlayer:
    """Slot player on the testbench pins. One slot lasts quarter_ns; SDA is sampled
    in the middle. With burst set, slots are cut into bursts like the PIO player
    does and the bus rests gap_ns between them."""

    def __init__(self, dut, quarter_ns=250, burst=None, gap_ns=20_000):
        self.dut = dut
        self.q = quarter_ns
        self.burst = burst
        self.gap = gap_ns
        self.slots = 0
        self.run = resume(self._run)
        self.wait_us = resume(self._wait_us)

    async def _run(self, slots):
        d = self.dut
        out = []
        for part in split_bursts(slots, self.burst) if self.burst else [slots]:
            for s in part:
                d.i3c_scl_drv.value = s >> 2
                if s & 3 == Z:
                    d.i3c_sda_oe.value = 0
                else:
                    d.i3c_sda_out.value = s & 3
                    d.i3c_sda_oe.value = 1
                await Timer(self.q / 2, unit="ns")
                out.append(int(d.i3c_sda.value))
                await Timer(self.q / 2, unit="ns")
            if self.burst:
                await Timer(self.gap, unit="ns")
        self.slots += len(slots)
        return out

    async def _wait_us(self, us):
        await Timer(us, unit="us")


class SimBoard:
    def __init__(self, dut):
        self.dut = dut
        self.reset = resume(self._reset)
        self.set_ui = resume(self._set_ui)
        self.uo = resume(self._uo)

    async def _reset(self):
        d = self.dut
        d.rst_n.value = 0
        await ClockCycles(d.clk, 5)
        await FallingEdge(d.clk)
        d.rst_n.value = 1
        await ClockCycles(d.clk, 5)

    async def _set_ui(self, value):
        self.dut.ui_in.value = value

    async def _uo(self):
        await ClockCycles(self.dut.clk, 8)  # let the synchronisers catch up with the last slot
        return int(self.dut.uo_out.value)


class BusWatch:
    """Records any cycle where the bridge fights or drives a line it must not."""

    def __init__(self, dut):
        self.dut = dut
        self.faults = []
        cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            await FallingEdge(d.clk)
            if not int(d.rst_n.value):
                continue
            if int(d.i3c_sda_conflict.value):
                self.faults.append("I3C SDA conflict")
            if int(d.i3c_scl_driven.value):
                self.faults.append("bridge drove I3C SCL")
            if int(d.i2c_push_pull_violation.value):
                self.faults.append("bridge drove an I2C line high")
            if int(d.uio_oe.value) & 0x33:
                self.faults.append("spare uio pin driven")


async def setup(dut, sensor=True):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in_drv.value = 0
    dut.i2c_scl_pull.value = 0
    dut.i2c_sda_pull.value = 0
    dut.i3c_scl_drv.value = 1
    dut.i3c_sda_oe.value = 0
    dut.i3c_sda_out.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    tgt = None
    if sensor:
        tgt = I2CTarget(dut.i2c_scl, dut.i2c_sda, dut.i2c_sda_pull, address=SENSOR).start()
        tgt.regs[0:2] = bytes([0x19, 0x80])  # temperature register
    return SimBoard(dut), BusWatch(dut), tgt


async def checklist(dut, player, board, **kw):
    lines = []
    report = await bridge(bringup.run_all)(board, player, da=DA, sensor=SENSOR, out=lines.append, **kw)
    for line in lines:
        dut._log.info(line)
    assert len(report.results) >= 25, len(report.results)
    assert report.failed == [], report.failed
    return report, lines


@cocotb.test()
async def test_bringup_with_sensor(dut):
    board, watch, tgt = await setup(dut)
    report, lines = await checklist(dut, SimPlayer(dut), board, expect=[0x19, 0x80])
    assert any("PID 0x" in line and "DA 0x09" in line for line in lines)
    assert ["R", [0x19, 0x80]] in tgt.log and ["W", [0x00]] in tgt.log
    assert watch.faults == []


@cocotb.test()
async def test_bringup_without_sensor(dut):
    board, watch, _ = await setup(dut, sensor=False)
    report, lines = await checklist(dut, SimPlayer(dut), board, i2c_fast=True, inst=1)
    assert any("no device answered" in line for line in lines)
    assert watch.faults == []


@cocotb.test()
async def test_bringup_in_pio_bursts(dut):
    """Same checklist, played the way pio_player.py does: at most 32 slots back to
    back at 1 MHz, with a pause between bursts."""
    board, watch, _ = await setup(dut)
    await checklist(dut, SimPlayer(dut, burst=32), board, expect=[0x19, 0x80], inst=3)
    assert watch.faults == []


@cocotb.test()
async def test_bridge_client(dut):
    board, watch, tgt = await setup(dut)
    tgt.regs[0:6] = bytes([1, 2, 3, 4, 5, 6])
    player = SimPlayer(dut)

    def session():
        board.set_ui(bringup.I2C_FAST)
        board.reset()
        i3c = I3CController(player)
        assert i3c.entdaa([DA])[0][3:] == (DA, True)
        br = Bridge(i3c, DA)
        assert br.write_read(SENSOR, 0x00, 4) == [1, 2, 3, 4]
        assert br.read(SENSOR, 2) == [5, 6]
        assert br.write(SENSOR, [0x02, 0xAA, 0xBB]) == 0x00
        assert br.write_read(SENSOR, 0x02, 2) == [0xAA, 0xBB]
        assert br.status() == 0x00
        assert br.scan(0x46, 0x4A) == [SENSOR]
        assert br.status() == NACK  # the last scanned address did not answer
        return bringup.sweep(lambda hz: SimPlayer(dut, quarter_ns=250e6 / hz), DA,
                             rates=(100_000, 400_000, 1_000_000), rounds=3, out=lambda s: None)

    rates = await bridge(session)()
    assert rates == {100_000: 3, 400_000: 3, 1_000_000: 3}, rates
    assert watch.faults == []


@cocotb.test()
async def test_split_bursts(dut):
    """Bursts keep every slot, respect the limit and end with SCL low when they can."""
    player = SimPlayer(dut)
    player.run = lambda slots: seen.extend(slots) or [1] * len(slots)
    seen = []
    i3c = I3CController(player)
    i3c.private_write(0x09, [0x81, 0x48, 0x00])
    for limit in (8, 32):
        parts = split_bursts(seen, limit)
        assert [s for p in parts for s in p] == seen
        assert all(0 < len(p) <= limit for p in parts)
        assert all(p[-1] >> 2 == 0 for p in parts[:-1])
    await Timer(1, unit="ns")
