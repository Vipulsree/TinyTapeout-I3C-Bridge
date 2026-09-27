# SPDX-License-Identifier: Apache-2.0
"""Two bridges on one I3C bus: ENTDAA arbitration by Provisioned ID, both
addresses usable afterwards, RSTDAA clearing both, and no SDA fights."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

from models.i3c_controller import I3CController


def pid(inst):
    return (0x7FFF << 33) | (0x0001 << 16) | (inst << 12)


async def setup(dut, inst_a, inst_b):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    dut.inst_a.value, dut.inst_b.value = inst_a, inst_b
    ctl = I3CController(dut.i3c_scl_drv, dut.i3c_sda_oe, dut.i3c_sda_out, dut.i3c_sda, period_ns=1000)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    faults = []

    async def watch():
        while True:
            await FallingEdge(dut.clk)
            if int(dut.i3c_sda_conflict.value):
                faults.append("SDA conflict")

    cocotb.start_soon(watch())
    return ctl, faults


def da_valid(dut):
    return (int(dut.uo_a.value) >> 4) & 1, (int(dut.uo_b.value) >> 4) & 1


async def status(ctl, da):
    assert await ctl.private_write(da, [0xC0, 0x00])
    for _ in range(20):
        out = await ctl.private_read(da)
        if out is not None:
            return out
    raise AssertionError(f"no response from {da:#x}")


@cocotb.test()
async def test_lowest_pid_wins_first(dut):
    ctl, faults = await setup(dut, inst_a=0b10, inst_b=0b01)
    found = await ctl.entdaa([0x10, 0x11, 0x12])
    # B has the lower PID (instance 01 < 10), so it wins the first round
    assert [(f[0], f[3], f[4]) for f in found] == [(pid(0b01), 0x10, True), (pid(0b10), 0x11, True)]
    assert da_valid(dut) == (1, 1)
    assert await status(ctl, 0x10) == [0x00] and await status(ctl, 0x11) == [0x00]
    assert await ctl.private_read(0x12) is None
    assert faults == []


@cocotb.test()
async def test_rstdaa_then_reassign(dut):
    ctl, faults = await setup(dut, inst_a=0b00, inst_b=0b11)
    await ctl.entdaa([0x20, 0x21])
    assert da_valid(dut) == (1, 1)
    assert await ctl.rstdaa()
    assert da_valid(dut) == (0, 0)
    found = await ctl.entdaa([0x30, 0x31])
    assert [f[0] for f in found] == [pid(0b00), pid(0b11)]
    assert await status(ctl, 0x30) == [0x00] and await status(ctl, 0x31) == [0x00]
    assert faults == []
