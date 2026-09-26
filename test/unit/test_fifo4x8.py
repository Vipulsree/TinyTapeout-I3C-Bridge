# SPDX-License-Identifier: Apache-2.0
"""Unit tests for fifo4x8. Inputs change on falling edges; outputs are checked there too."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    dut.clr.value = 0
    dut.push.value = 0
    dut.pop.value = 0
    dut.wdata.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def push(dut, v):
    dut.wdata.value = v
    dut.push.value = 1
    await FallingEdge(dut.clk)
    dut.push.value = 0


async def pop(dut):
    v = int(dut.rdata.value)
    dut.pop.value = 1
    await FallingEdge(dut.clk)
    dut.pop.value = 0
    return v


@cocotb.test()
async def test_order_and_flags(dut):
    await setup(dut)
    assert int(dut.empty.value) == 1 and int(dut.rdata.value) == 0
    for v in (0x11, 0x22, 0x33, 0x44):
        await push(dut, v)
    assert int(dut.full.value) == 1 and int(dut.count.value) == 4
    assert [await pop(dut) for _ in range(4)] == [0x11, 0x22, 0x33, 0x44]
    assert int(dut.empty.value) == 1 and int(dut.count.value) == 0


@cocotb.test()
async def test_push_when_full_is_dropped(dut):
    await setup(dut)
    for v in (1, 2, 3, 4, 5):
        await push(dut, v)
    assert int(dut.count.value) == 4
    assert [await pop(dut) for _ in range(4)] == [1, 2, 3, 4]


@cocotb.test()
async def test_pop_when_empty_is_ignored_and_reads_zero(dut):
    await setup(dut)
    assert await pop(dut) == 0
    assert int(dut.count.value) == 0
    await push(dut, 0xAB)
    assert await pop(dut) == 0xAB


@cocotb.test()
async def test_push_and_pop_together_when_full(dut):
    await setup(dut)
    for v in (1, 2, 3, 4):
        await push(dut, v)
    dut.wdata.value = 9
    dut.push.value = 1
    dut.pop.value = 1
    await FallingEdge(dut.clk)
    dut.push.value = 0
    dut.pop.value = 0
    assert int(dut.count.value) == 4
    assert [await pop(dut) for _ in range(4)] == [2, 3, 4, 9]


@cocotb.test()
async def test_clear(dut):
    await setup(dut)
    await push(dut, 7)
    await push(dut, 8)
    dut.clr.value = 1
    await FallingEdge(dut.clk)
    dut.clr.value = 0
    assert int(dut.empty.value) == 1 and int(dut.rdata.value) == 0
    await push(dut, 0x5A)
    assert await pop(dut) == 0x5A
