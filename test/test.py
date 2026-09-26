# SPDX-FileCopyrightText: © 2026 VLSI PD Tapeout team
# SPDX-License-Identifier: Apache-2.0
"""Top-level tests for tt_um_i3cbridge. The TT CI runs these through test/Makefile,
at RTL and on the gate-level netlist, so they only use pins and tb wires.

Week-2 scope: reset state, the bus-condition scaffolding on DBG_STATE, and the
rule that the bridge never fights the bus. Target tests arrive with i3c_tgt."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

from models.i3c_controller import BROADCAST, I3CController

CLK_NS = 40  # 25 MHz


class BusWatch:
    """Records any cycle where the bridge fights or drives a line it must not."""

    def __init__(self, dut):
        self.dut = dut
        self.faults = []

    async def run(self):
        d = self.dut
        while True:
            await FallingEdge(d.clk)
            if int(d.i3c_sda_conflict.value):
                self.faults.append("I3C SDA conflict")
            if int(d.i3c_scl_driven.value):
                self.faults.append("bridge drove I3C SCL")
            if int(d.i2c_push_pull_violation.value):
                self.faults.append("bridge drove an I2C line high")


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in_drv.value = 0
    dut.i2c_scl_pull.value = 0
    dut.i2c_sda_pull.value = 0
    ctl = I3CController(dut.i3c_scl_drv, dut.i3c_sda_oe, dut.i3c_sda_out, dut.i3c_sda, period_ns=1000)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    await FallingEdge(dut.clk)
    assert int(dut.uio_oe.value) == 0
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    watch = BusWatch(dut)
    cocotb.start_soon(watch.run())
    return ctl, watch


def dbg(dut):
    v = int(dut.uo_out.value)
    return {"in_xfer": v & 1, "n_start": (v >> 1) & 3, "hdr": (v >> 3) & 1, "status": v >> 4}


@cocotb.test()
async def test_reset_state(dut):
    ctl, watch = await reset(dut)
    assert int(dut.uo_out.value) == 0  # DA_VALID, IRQ, BUSY, ERR low; DBG idle
    assert int(dut.uio_oe.value) == 0
    assert int(dut.i3c_sda.value) == 1 and int(dut.i2c_scl.value) == 1 and int(dut.i2c_sda.value) == 1


@cocotb.test()
async def test_bus_conditions_on_dbg(dut):
    ctl, watch = await reset(dut)
    await ctl.start()
    assert dbg(dut)["in_xfer"] == 1 and dbg(dut)["n_start"] == 1
    await ctl.header(BROADCAST, 0)
    await ctl.rstart()
    await ClockCycles(dut.clk, 5)
    assert dbg(dut)["n_start"] == 2  # repeated START counted
    await ctl.header(0x08, 1)
    await ctl.stop()
    assert dbg(dut)["in_xfer"] == 0
    assert watch.faults == []


@cocotb.test()
async def test_hdr_exit_on_dbg(dut):
    ctl, watch = await reset(dut)
    await ctl.enthdr(0)
    await ctl.hdr_traffic(200, random.Random(7))
    await ClockCycles(dut.clk, 5)
    assert dbg(dut)["hdr"] == 0, "HDR traffic was mistaken for the exit pattern"
    await ctl.hdr_exit()
    await ClockCycles(dut.clk, 5)
    assert dbg(dut)["hdr"] == 1 and dbg(dut)["in_xfer"] == 0
    assert watch.faults == []


@cocotb.test()
async def test_bridge_stays_off_the_bus(dut):
    ctl, watch = await reset(dut)
    for da in (0x08, 0x09):
        await ctl.private_write(da, [0xA5, 0x5A], use_7e=True)
        assert await ctl.private_read(da) is None  # no target yet: NACK
    await ctl.rstdaa()
    await ctl.entdaa([0x08])
    assert dbg(dut)["status"] == 0  # DA_VALID, IRQ, BUSY, ERR all low
    assert watch.faults == []
