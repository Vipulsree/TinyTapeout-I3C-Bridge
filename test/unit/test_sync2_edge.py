# SPDX-License-Identifier: Apache-2.0
"""Unit tests for sync2_edge, built with N=2, INIT=2'b11, FILTER=2'b10.
Bit 0 is unfiltered; bit 1 has the two-sample glitch filter."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    dut.d.value = 0b11
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def watch(dut, bit, cycles):
    """Return (q samples, rise count, fall count) over the next cycles."""
    qs, rises, falls = [], 0, 0
    for _ in range(cycles):
        await FallingEdge(dut.clk)
        qs.append((int(dut.q.value) >> bit) & 1)
        rises += (int(dut.rise.value) >> bit) & 1
        falls += (int(dut.fall.value) >> bit) & 1
    return qs, rises, falls


@cocotb.test()
async def test_unfiltered_edge_latency(dut):
    await setup(dut)
    dut.d.value = 0b10  # bit 0 falls
    qs, rises, falls = await watch(dut, 0, 6)
    assert qs.index(0) == 1, f"q[0] samples {qs}"  # visible 2 clocks after the pin changes
    assert (rises, falls) == (0, 1)
    dut.d.value = 0b11
    qs, rises, falls = await watch(dut, 0, 6)
    assert (rises, falls) == (1, 0)


@cocotb.test()
async def test_filter_rejects_one_cycle_glitch(dut):
    await setup(dut)
    dut.d.value = 0b01  # bit 1 low for exactly one clock
    await FallingEdge(dut.clk)
    dut.d.value = 0b11
    qs, rises, falls = await watch(dut, 1, 8)
    assert all(qs) and (rises, falls) == (0, 0), f"q[1] {qs}"


@cocotb.test()
async def test_filter_passes_two_cycle_change(dut):
    await setup(dut)
    dut.d.value = 0b01
    qs, rises, falls = await watch(dut, 1, 8)
    assert qs[-1] == 0 and falls == 1 and rises == 0, f"q[1] {qs}"
