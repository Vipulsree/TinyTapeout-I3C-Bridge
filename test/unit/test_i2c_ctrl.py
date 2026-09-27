# SPDX-License-Identifier: Apache-2.0
"""Unit tests for i2c_ctrl against the Python I2C target model: write, read,
write-then-read with repeated START, NACK, both SCL rates, clock stretching and
abort. The test plays cmd_ctrl (a list stands in for the FIFO)."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer
from cocotb.utils import get_sim_time

from models.i2c_target import I2CTarget

OP_WRITE, OP_READ, OP_WRRD = range(3)
SENSOR = 0x48


class Env:
    def __init__(self, dut):
        self.dut = dut
        self.fifo = []
        self.pushed = []
        self.done = []

    async def setup(self, fast=1):
        d = self.dut
        cocotb.start_soon(Clock(d.clk, 40, unit="ns").start())
        for name in ("d_start", "d_abort", "d_op", "d_len", "d_addr", "d_wr_data", "ext_scl_pull",
                     "ext_sda_pull"):
            getattr(d, name).value = 0
        d.fast.value = fast
        d.rst_n.value = 0
        await ClockCycles(d.clk, 3)
        await FallingEdge(d.clk)
        d.rst_n.value = 1
        cocotb.start_soon(self._io())
        return self

    async def _io(self):
        # FIFO head changes just after the rising edge, like fifo4x8; pulses are
        # sampled mid-cycle and take effect at the next rising edge.
        d = self.dut
        while True:
            await RisingEdge(d.clk)
            d.d_wr_data.value = self.fifo[0] if self.fifo else 0
            await FallingEdge(d.clk)
            if int(d.d_wr_pop.value):
                self.fifo.pop(0)
            if int(d.d_rd_push.value):
                self.pushed.append(int(d.d_rd_data.value))
            if int(d.d_done.value):
                self.done.append(int(d.d_nack.value))

    async def run(self, op, length, addr=SENSOR, data=(), timeout_us=2000):
        d = self.dut
        self.fifo, self.pushed, self.done = list(data), [], []
        await RisingEdge(d.clk)
        d.d_wr_data.value = self.fifo[0] if self.fifo else 0
        d.d_op.value, d.d_len.value, d.d_addr.value, d.d_start.value = op, length, addr, 1
        await RisingEdge(d.clk)
        d.d_start.value = 0
        for _ in range(timeout_us):
            if self.done:
                return self.done[0] == 0
            await Timer(1, unit="us")
        raise AssertionError("controller never finished")


def sensor(dut):
    tgt = I2CTarget(dut.scl, dut.sda, dut.ext_sda_pull, address=SENSOR).start()
    tgt.regs[0:8] = bytes([0x19, 0x80, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66])
    return tgt


@cocotb.test()
async def test_write(dut):
    env = await Env(dut).setup()
    tgt = sensor(dut)
    assert await env.run(OP_WRITE, 4, data=[0x04, 0xA1, 0xB2, 0xC3])
    assert tgt.log == [["W", [0x04, 0xA1, 0xB2, 0xC3]]] and env.fifo == []


@cocotb.test()
async def test_read_and_write_then_read(dut):
    env = await Env(dut).setup()
    tgt = sensor(dut)
    assert await env.run(OP_WRRD, 4, data=[0x02])
    assert env.pushed == [0x11, 0x22, 0x33, 0x44]
    assert await env.run(OP_READ, 2)
    assert env.pushed == [0x55, 0x66]
    assert tgt.log == [["W", [0x02]], ["R", [0x11, 0x22, 0x33, 0x44]], ["R", [0x55, 0x66]]]


@cocotb.test()
async def test_nack(dut):
    env = await Env(dut).setup()
    tgt = sensor(dut)
    assert not await env.run(OP_WRITE, 2, addr=0x49, data=[0x00, 0x01])
    assert env.fifo == [0x00, 0x01]
    tgt.present = False
    assert not await env.run(OP_WRRD, 1, data=[0x00])
    assert env.pushed == []
    await ClockCycles(dut.clk, 20)
    assert int(dut.scl.value) == 1 and int(dut.sda.value) == 1


@cocotb.test()
async def test_scl_rates(dut):
    env = await Env(dut).setup()
    sensor(dut)
    for fast, period_ns in ((0, 63 * 4 * 40), (1, 17 * 4 * 40)):
        dut.fast.value = fast
        task = cocotb.start_soon(env.run(OP_WRITE, 1, data=[0x00], timeout_us=4000))
        await RisingEdge(dut.scl)
        await RisingEdge(dut.scl)
        t0 = get_sim_time(unit="ns")
        await RisingEdge(dut.scl)
        period = get_sim_time(unit="ns") - t0
        assert period_ns <= period <= period_ns + 5 * 40, f"fast={fast}: period {period} ns"
        assert await task


@cocotb.test()
async def test_clock_stretching(dut):
    env = await Env(dut).setup()
    tgt = sensor(dut)

    async def stretch():
        for _ in range(3):
            await FallingEdge(dut.scl)
            await Timer(200, unit="ns")
            dut.ext_scl_pull.value = 1
            await Timer(20, unit="us")
            dut.ext_scl_pull.value = 0
            await Timer(5, unit="us")

    cocotb.start_soon(stretch())
    assert await env.run(OP_WRRD, 2, data=[0x00])
    assert env.pushed == [0x19, 0x80] and tgt.log[-1] == ["R", [0x19, 0x80]]


@cocotb.test()
async def test_abort_releases_bus(dut):
    env = await Env(dut).setup()
    sensor(dut)
    task = cocotb.start_soon(env.run(OP_WRITE, 1, data=[0x00], timeout_us=200))
    await FallingEdge(dut.scl)
    dut.ext_scl_pull.value = 1
    await Timer(30, unit="us")
    await RisingEdge(dut.clk)
    dut.d_abort.value = 1
    await RisingEdge(dut.clk)
    dut.d_abort.value = 0
    await Timer(20, unit="us")
    dut.ext_scl_pull.value = 0
    await Timer(5, unit="us")
    assert int(dut.idle.value) == 1 and env.done == []
    assert int(dut.scl.value) == 1 and int(dut.sda.value) == 1
    task.cancel()
