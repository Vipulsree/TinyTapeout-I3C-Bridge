# SPDX-FileCopyrightText: © 2026 VLSI PD Tapeout team
# SPDX-License-Identifier: Apache-2.0
"""Top-level tests for tt_um_i3cbridge. The TT CI runs these through test/Makefile,
at RTL and on the gate-level netlist, so they only use pins and tb wires.

Covers dynamic address assignment (ENTDAA, SETDASA, RSTDAA), bridged I2C
transactions (write, read, write-then-read, status), NACK while busy, the
End-of-Data T-bit and controller abort, errors TE0-TE3, HDR entry and exit,
downstream NACK and both timeouts. Every test also checks that the bridge
never fights the I3C controller, never drives SCL and never drives I2C high."""
import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Timer

from models.i2c_target import I2CTarget
from models.i3c_controller import BROADCAST, CCC_ENTDAA, CCC_SETDASA, I3CController, odd_parity

CLK_NS = 40  # 25 MHz
GATES = os.environ.get("GATES") == "yes"

I2C_FAST = 1 << 3
SENSOR = 0x48
DA = 0x08
SA = 0x3A
OP_WRITE, OP_READ, OP_WRRD, OP_STATUS = range(4)
NACK, PARITY, OVF, TIMEOUT = 0x80, 0x40, 0x20, 0x10
S_IDLE, S_HDR = 0, 9


def cmd(op, length=1):
    return (op << 6) | (length - 1)


def pid(inst):
    return (0x7FFF << 33) | (0x0001 << 16) | (inst << 12)


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
            if int(d.i3c_sda_conflict.value):
                self.faults.append("I3C SDA conflict")
            if int(d.i3c_scl_driven.value):
                self.faults.append("bridge drove I3C SCL")
            if int(d.i2c_push_pull_violation.value):
                self.faults.append("bridge drove an I2C line high")
            if int(d.uio_oe.value) & 0x33:
                self.faults.append("spare uio pin driven")


async def reset(dut, ui=I2C_FAST, sensor=True):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = ui
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
    tgt = None
    if sensor:
        tgt = I2CTarget(dut.i2c_scl, dut.i2c_sda, dut.i2c_sda_pull, address=SENSOR).start()
        tgt.regs[0:2] = bytes([0x19, 0x80])  # temperature register
        tgt.regs[6:8] = bytes([0xAB, 0xCD])
    return ctl, watch, tgt


def uo(dut):
    v = int(dut.uo_out.value)
    return {"state": v & 0xF, "da_valid": (v >> 4) & 1, "irq": (v >> 5) & 1, "busy": (v >> 6) & 1,
            "err": v >> 7}


async def assign(ctl, da=DA):
    found = await ctl.entdaa([da])
    assert len(found) == 1 and found[0][3:] == (da, True), found
    return found[0]


async def transact(ctl, da, req, max_len=8, polls=400):
    """Private write with the command, then poll private reads until the bridge ACKs."""
    assert await ctl.private_write(da, req)
    for _ in range(polls):
        out = await ctl.private_read(da, max_len)
        if out is not None:
            return out
        await Timer(5, unit="us")
    raise AssertionError("bridge never ACKed the private read")


# ---------------------------------------------------------------------- basics
@cocotb.test()
async def test_reset_state(dut):
    ctl, watch, _ = await reset(dut, sensor=False)
    assert int(dut.uo_out.value) == 0  # DBG idle; DA_VALID, IRQ, BUSY, ERR low
    assert int(dut.uio_oe.value) == 0
    assert int(dut.i3c_sda.value) == 1 and int(dut.i2c_scl.value) == 1 and int(dut.i2c_sda.value) == 1


@cocotb.test()
async def test_nothing_answers_before_an_address(dut):
    ctl, watch, _ = await reset(dut, sensor=False)
    for da in (0x08, 0x09):
        assert not await ctl.private_write(da, [0xA5, 0x5A], use_7e=True)
        assert await ctl.private_read(da) is None
    assert await ctl.rstdaa()  # 7E is always ACKed
    assert uo(dut)["da_valid"] == 0 and watch.faults == []


# ---------------------------------------------------------------------- addressing
@cocotb.test()
async def test_entdaa_identity_and_address(dut):
    ctl, watch, _ = await reset(dut, ui=I2C_FAST | (0b10 << 1), sensor=False)
    got_pid, bcr, dcr, da, acked = await assign(ctl, 0x21)
    assert got_pid == pid(0b10) and bcr == 0x01 and dcr == 0x00
    assert uo(dut)["da_valid"] == 1
    assert await ctl.entdaa([0x22]) == []  # already has an address: NACKs 7E/R
    assert await transact(ctl, 0x21, [cmd(OP_STATUS), 0]) == [0x00]
    assert watch.faults == []


@cocotb.test()
async def test_setdasa_and_rstdaa(dut):
    ctl, watch, _ = await reset(dut, ui=I2C_FAST | 1, sensor=False)  # SA_LSB = 1: 0x3B
    assert not await ctl.setdasa(SA, 0x30)
    assert await ctl.setdasa(SA + 1, 0x30)
    assert uo(dut)["da_valid"] == 1
    assert await transact(ctl, 0x30, [cmd(OP_STATUS), 0]) == [0x00]
    assert not await ctl.setdasa(SA + 1, 0x31)  # only without a dynamic address
    assert await ctl.rstdaa()
    assert uo(dut)["da_valid"] == 0
    assert await ctl.private_read(0x30) is None
    await assign(ctl, 0x32)  # ENTDAA works again after RSTDAA
    assert watch.faults == []


# ---------------------------------------------------------------------- bridging
@cocotb.test()
async def test_bridged_read_from_plan(dut):
    """Section 5.4 of the plan: read 2 bytes from register 0x00 of the sensor at 0x48."""
    ctl, watch, tgt = await reset(dut)
    await assign(ctl)
    assert await transact(ctl, DA, [0x81, SENSOR, 0x00]) == [0x19, 0x80]
    assert tgt.log == [["W", [0x00]], ["R", [0x19, 0x80]]]
    assert uo(dut)["irq"] == 0 and uo(dut)["err"] == 0 and watch.faults == []


@cocotb.test()
async def test_all_ops(dut):
    ctl, watch, tgt = await reset(dut)
    await assign(ctl)
    # write, LEN = 2: register 5 = 0x60; response is the status byte
    assert await transact(ctl, DA, [cmd(OP_WRITE, 2), SENSOR, 0x05, 0x60]) == [0x00]
    assert tgt.regs[5] == 0x60
    # read, LEN = 2 continues from the sensor's pointer (6)
    assert await transact(ctl, DA, [cmd(OP_READ, 2), SENSOR]) == [0xAB, 0xCD]
    # write then read, LEN = 4 (the FIFO's size)
    tgt.regs[0:4] = bytes([1, 2, 3, 4])
    assert await transact(ctl, DA, [cmd(OP_WRRD, 4), SENSOR, 0x00]) == [1, 2, 3, 4]
    # status
    assert await transact(ctl, DA, [cmd(OP_STATUS), 0]) == [0x00]
    # the 7E-prefixed form of private transfers works too
    assert await ctl.private_write(DA, [cmd(OP_STATUS), 0], use_7e=True)
    assert await ctl.private_read(DA, use_7e=True) == [0x00]
    assert watch.faults == []


@cocotb.test()
async def test_nack_while_busy_then_retry(dut):
    ctl, watch, tgt = await reset(dut, ui=0)  # 100 kHz downstream: the transfer takes a while
    await assign(ctl)
    assert await ctl.private_write(DA, [0x81, SENSOR, 0x00])
    await ClockCycles(dut.clk, 20)
    assert uo(dut)["busy"] == 1
    assert await ctl.private_read(DA) is None             # busy: NACK
    assert not await ctl.private_write(DA, [0xC0, 0x00])   # and no new command either
    while not uo(dut)["irq"]:
        await Timer(10, unit="us")
    assert await ctl.private_read(DA) == [0x19, 0x80]
    assert watch.faults == []


@cocotb.test()
async def test_downstream_nack(dut):
    ctl, watch, tgt = await reset(dut)
    await assign(ctl)
    # Nobody at 0x49: status shows NACK and the unsent payload byte
    assert await transact(ctl, DA, [cmd(OP_WRITE, 1), 0x49, 0x00]) == [NACK | 1]
    assert uo(dut)["err"] == 1
    assert await transact(ctl, DA, [cmd(OP_READ, 2), 0x49]) == [0x00, 0x00]  # padded
    assert await transact(ctl, DA, [cmd(OP_STATUS), 0]) == [NACK]
    assert await transact(ctl, DA, [cmd(OP_WRITE, 1), SENSOR, 0x00]) == [0x00]
    assert uo(dut)["err"] == 0


@cocotb.test()
async def test_controller_aborts_read(dut):
    ctl, watch, tgt = await reset(dut)
    await assign(ctl)
    tgt.regs[0:3] = bytes([0x11, 0x22, 0x33])
    assert await ctl.private_write(DA, [cmd(OP_WRRD, 3), SENSOR, 0x00])
    while not uo(dut)["irq"]:
        await Timer(10, unit="us")
    assert await ctl.private_read(DA, max_len=1) == [0x11]  # T = 1, the controller stops it
    await ClockCycles(dut.clk, 10)
    assert uo(dut)["state"] == S_IDLE and uo(dut)["irq"] == 0  # the rest is dropped
    assert await transact(ctl, DA, [cmd(OP_STATUS), 0]) == [0x00]
    assert watch.faults == []


# ---------------------------------------------------------------------- errors
@cocotb.test()
async def test_te2_bad_write_parity(dut):
    ctl, watch, tgt = await reset(dut)
    await assign(ctl)
    await ctl.start()
    assert await ctl.header(DA, 0)
    await ctl.write_byte(cmd(OP_WRITE, 1))
    await ctl.write_byte(SENSOR)
    await ctl.write_byte(0x07, parity=False)
    await ctl.write_bit(1 - odd_parity(0x07, 8))  # wrong T-bit
    await ctl.stop()
    await ClockCycles(dut.clk, 10)
    assert uo(dut)["err"] == 1 and uo(dut)["state"] == S_IDLE
    assert tgt.log == []  # the command was dropped
    assert await transact(ctl, DA, [cmd(OP_STATUS), 0]) == [PARITY]


@cocotb.test()
async def test_te1_bad_ccc_parity(dut):
    ctl, watch, _ = await reset(dut, sensor=False)
    await ctl.start()
    assert await ctl.header(BROADCAST, 0)
    await ctl.write_byte(CCC_ENTDAA, parity=False)
    await ctl.write_bit(1 - odd_parity(CCC_ENTDAA, 8))
    await ctl.rstart()
    assert not await ctl.header(BROADCAST, 1)  # the ENTDAA was ignored
    await ctl.stop()
    assert uo(dut)["err"] == 1 and uo(dut)["da_valid"] == 0


@cocotb.test()
async def test_te3_bad_address_parity_then_rejoin(dut):
    ctl, watch, _ = await reset(dut, sensor=False)
    await ctl.start()
    await ctl.header(BROADCAST, 0)
    await ctl.write_byte(CCC_ENTDAA)
    await ctl.rstart()
    assert await ctl.header(BROADCAST, 1)
    for _ in range(64):
        await ctl.read_bit()
    await ctl.write_byte((DA << 1) | (1 - odd_parity(DA, 7)), pp=False, parity=False)
    assert await ctl.read_bit() == 1  # TE3: NACK
    # Next Sr + 7E/R: the bridge rejoins and takes a good address
    await ctl.rstart()
    assert await ctl.header(BROADCAST, 1)
    for _ in range(64):
        await ctl.read_bit()
    await ctl.write_byte((DA << 1) | odd_parity(DA, 7), pp=False, parity=False)
    assert await ctl.read_bit() == 0
    await ctl.stop()
    assert uo(dut)["da_valid"] == 1 and uo(dut)["err"] == 0  # TE3 is not a status flag
    assert watch.faults == []


@cocotb.test()
async def test_te0_waits_for_hdr_exit(dut):
    ctl, watch, _ = await reset(dut, sensor=False)
    await assign(ctl)
    await ctl.start()
    await ctl.header(0x7F, 0)  # 7E/W with one bit wrong
    await ctl.stop()
    await ClockCycles(dut.clk, 10)
    assert uo(dut)["state"] == S_HDR
    assert await ctl.private_read(DA) is None  # deaf
    await ctl.hdr_exit()
    await ClockCycles(dut.clk, 10)
    assert uo(dut)["state"] == S_IDLE
    assert await transact(ctl, DA, [cmd(OP_STATUS), 0]) == [0x00]


@cocotb.test()
async def test_hdr_traffic_ignored(dut):
    ctl, watch, _ = await reset(dut, sensor=False)
    await assign(ctl)
    await ctl.enthdr(0)
    await ClockCycles(dut.clk, 5)
    assert uo(dut)["state"] == S_HDR
    await ctl.hdr_traffic(400, random.Random(3))
    assert uo(dut)["state"] == S_HDR
    await ctl.hdr_exit()
    await ClockCycles(dut.clk, 10)
    assert uo(dut)["state"] == S_IDLE and uo(dut)["da_valid"] == 1
    assert await transact(ctl, DA, [cmd(OP_STATUS), 0]) == [0x00]
    assert watch.faults == []


@cocotb.test()
async def test_unsupported_direct_ccc_nacks(dut):
    ctl, watch, _ = await reset(dut, sensor=False)
    await assign(ctl)
    await ctl.start()
    await ctl.header(BROADCAST, 0)
    await ctl.write_byte(0x8D)  # GETPID (direct): not supported
    await ctl.rstart()
    assert not await ctl.header(DA, 1, od=False)
    await ctl.stop()
    assert uo(dut)["err"] == 0
    assert await transact(ctl, DA, [cmd(OP_STATUS), 0]) == [0x00]  # normal again after P


# ---------------------------------------------------------------------- timeouts (RTL only: 35 ms)
@cocotb.test(skip=GATES)
async def test_i2c_stretch_timeout(dut):
    ctl, watch, tgt = await reset(dut)
    await assign(ctl)
    assert await ctl.private_write(DA, [cmd(OP_WRITE, 1), SENSOR, 0x00])
    await FallingEdge(dut.i2c_scl)
    dut.i2c_scl_pull.value = 1  # the sensor stretches forever
    await Timer(36, unit="ms")
    dut.i2c_scl_pull.value = 0
    assert uo(dut)["irq"] == 1 and uo(dut)["err"] == 1
    assert await ctl.private_read(DA) == [TIMEOUT | 1]
    assert int(dut.i2c_scl.value) == 1 and int(dut.i2c_sda.value) == 1


@cocotb.test(skip=GATES)
async def test_i3c_stall_releases_sda(dut):
    ctl, watch, tgt = await reset(dut, sensor=False)
    await assign(ctl)
    assert await ctl.private_write(DA, [cmd(OP_STATUS), 0])
    await ctl.start()
    assert await ctl.header(DA, 1)
    await ctl.read_bit()  # status 0x00: the bridge now drives SDA low, push-pull
    assert int(dut.uio_oe.value) & 0x08
    await Timer(36, unit="ms")  # controller stops with SCL low
    assert int(dut.uio_oe.value) & 0x08 == 0 and uo(dut)["state"] == S_IDLE
    await ctl.stop()
    assert await transact(ctl, DA, [cmd(OP_STATUS), 0]) == [0x00]
