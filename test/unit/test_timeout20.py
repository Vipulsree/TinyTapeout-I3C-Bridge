# SPDX-License-Identifier: Apache-2.0
"""Unit tests for timeout20 (W = 20). Inputs change on falling edges."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge


async def setup(dut, limit):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    dut.run.value = 0
    dut.kick.value = 0
    dut.limit.value = limit
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def expiries(dut, cycles):
    """Falling-edge indexes (1-based) at which expired is high."""
    hits = []
    for i in range(1, cycles + 1):
        await FallingEdge(dut.clk)
        if int(dut.expired.value):
            hits.append(i)
    return hits


@cocotb.test()
async def test_expires_after_limit(dut):
    await setup(dut, 10)
    dut.run.value = 1
    hits = await expiries(dut, 12)
    assert hits and hits[0] == 10, f"expired at {hits}"
    assert 11 not in hits  # one-cycle pulse


@cocotb.test()
async def test_kick_restarts(dut):
    await setup(dut, 10)
    dut.run.value = 1
    for _ in range(8):  # activity every 8 cycles keeps it alive
        assert await expiries(dut, 7) == []
        dut.kick.value = 1
        await FallingEdge(dut.clk)
        dut.kick.value = 0
    hits = await expiries(dut, 12)
    assert hits and hits[0] == 10, f"expired at {hits} after the last kick"


@cocotb.test()
async def test_run_low_clears_the_count(dut):
    await setup(dut, 10)
    dut.run.value = 1
    assert await expiries(dut, 8) == []
    dut.run.value = 0
    await FallingEdge(dut.clk)
    dut.run.value = 1
    hits = await expiries(dut, 12)
    assert hits and hits[0] == 10


@cocotb.test()
async def test_zero_limit_disables(dut):
    await setup(dut, 0)
    dut.run.value = 1
    assert await expiries(dut, 300) == []


@cocotb.test()
async def test_full_20_bit_limit(dut):
    limit = (1 << 20) - 1  # 1,048,575 clocks = 41.9 ms at 25 MHz
    await setup(dut, limit)
    dut.run.value = 1
    await ClockCycles(dut.clk, limit - 1, rising=False)
    assert int(dut.expired.value) == 0
    await FallingEdge(dut.clk)
    assert int(dut.expired.value) == 1
