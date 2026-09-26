# SPDX-License-Identifier: Apache-2.0
"""Unit tests for clkdiv: tick spacing for the SPI and I2C settings."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    dut.en.value = 0
    dut.div_m1.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def tick_positions(dut, cycles):
    pos = []
    for i in range(cycles):
        if int(dut.tick.value):
            pos.append(i)
        await FallingEdge(dut.clk)
    return pos


@cocotb.test()
async def test_no_tick_when_disabled(dut):
    await setup(dut)
    dut.div_m1.value = 3
    assert await tick_positions(dut, 50) == []


@cocotb.test()
async def test_tick_period_matches_divider(dut):
    await setup(dut)
    # SPI half-periods (4 << SPI_DIV) and I2C quarter-periods (63, 17)
    for period in (4, 8, 16, 32, 63, 17):
        dut.en.value = 0
        dut.div_m1.value = period - 1
        await FallingEdge(dut.clk)
        dut.en.value = 1
        pos = await tick_positions(dut, period * 5 + 1)
        assert len(pos) == 5, f"period {period}: ticks at {pos}"
        gaps = {b - a for a, b in zip(pos, pos[1:])}
        assert gaps == {period}, f"period {period}: gaps {gaps}"
        assert pos[0] == period - 1, f"period {period}: first tick at {pos[0]}"


@cocotb.test()
async def test_disable_restarts_phase(dut):
    await setup(dut)
    dut.div_m1.value = 7
    dut.en.value = 1
    await ClockCycles(dut.clk, 5)
    await FallingEdge(dut.clk)
    dut.en.value = 0
    await FallingEdge(dut.clk)
    dut.en.value = 1
    pos = await tick_positions(dut, 20)
    assert pos[0] == 7
