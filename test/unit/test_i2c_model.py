# SPDX-License-Identifier: Apache-2.0
"""Checks the Python I2C target model with the bit-banged I2C controller,
so later RTL tests can trust both."""
import cocotb
from cocotb.triggers import Timer

from models.i2c_controller import I2CController
from models.i2c_target import I2CTarget


def make(dut, address=0x48):
    dut.tgt_sda_pull.value = 0
    tgt = I2CTarget(dut.scl, dut.sda, dut.tgt_sda_pull, address=address).start()
    ctl = I2CController(dut.ctrl_scl_pull, dut.ctrl_sda_pull, dut.scl, dut.sda, period_ns=10_000)
    return tgt, ctl


@cocotb.test()
async def test_write_then_read_back(dut):
    tgt, ctl = make(dut)
    await Timer(1, unit="us")
    assert await ctl.write(0x48, [0x05, 0xA5, 0x5A])
    assert tgt.regs[5] == 0xA5 and tgt.regs[6] == 0x5A
    assert await ctl.write_read(0x48, [0x05], 2) == [0xA5, 0x5A]
    assert tgt.log == [["W", [0x05, 0xA5, 0x5A]], ["W", [0x05]], ["R", [0xA5, 0x5A]]]


@cocotb.test()
async def test_sequential_read(dut):
    tgt, ctl = make(dut)
    tgt.regs[0:4] = bytes([0x10, 0x20, 0x30, 0x40])
    await Timer(1, unit="us")
    assert await ctl.write(0x48, [0x00])
    assert await ctl.read(0x48, 4) == [0x10, 0x20, 0x30, 0x40]


@cocotb.test()
async def test_wrong_address_and_absent_device_nack(dut):
    tgt, ctl = make(dut)
    await Timer(1, unit="us")
    assert not await ctl.write(0x49, [0x00])
    tgt.present = False
    assert not await ctl.write(0x48, [0x00])
    assert await ctl.read(0x48, 1) is None
    assert tgt.log == []
