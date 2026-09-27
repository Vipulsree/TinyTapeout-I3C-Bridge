# SPDX-License-Identifier: Apache-2.0
"""Unit tests for Track B's cmd_ctrl. The test plays the I3C target (private
write bytes, frame starts / ends, takes) and a fake I2C controller that answers
d_start. Inputs change just after rising edges, outputs are sampled mid-cycle."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

S_IDLE, S_HEADER, S_WRITE, S_EXEC, S_RESPOND = range(5)
OP_WRITE, OP_READ, OP_WRRD, OP_STATUS = range(4)
INPUTS = ("h_rx_data", "h_rx_valid", "h_frame_start", "h_frame_rd", "h_frame_end", "par_err", "h_tx_take",
          "d_done", "d_nack", "d_wr_pop", "d_rd_data", "d_rd_push", "bus_active", "bus_kick")
NACK, PARITY, OVF, TIMEOUT = 0x80, 0x40, 0x20, 0x10


def cmd(op, length=1):
    return (op << 6) | (length - 1)


class Env:
    def __init__(self, dut):
        self.dut = dut
        self.reads = []
        self.nack = False
        self.hang = False
        self.writes = []
        self.starts = []
        self.aborts = 0
        self.bus_timeouts = 0

    async def setup(self, limit=2000):
        d = self.dut
        cocotb.start_soon(Clock(d.clk, 40, unit="ns").start())
        for name in INPUTS:
            getattr(d, name).value = 0
        d.to_limit.value = limit
        d.rst_n.value = 0
        await ClockCycles(d.clk, 2)
        await RisingEdge(d.clk)
        d.rst_n.value = 1
        cocotb.start_soon(self._device())
        cocotb.start_soon(self._watch())
        return self

    async def _watch(self):
        while True:
            await FallingEdge(self.dut.clk)
            self.aborts += int(self.dut.d_abort.value)
            self.bus_timeouts += int(self.dut.bus_timeout.value)

    async def _device(self):
        d = self.dut
        while True:
            await FallingEdge(d.clk)
            if not int(d.d_start.value):
                continue
            op, ln = int(d.d_op.value), int(d.d_len.value)
            self.starts.append((op, ln, int(d.d_addr.value)))
            for _ in range({OP_WRITE: ln, OP_WRRD: 1}.get(op, 0)):
                await FallingEdge(d.clk)
                self.writes.append(int(d.d_wr_data.value))
                await self.pulse("d_wr_pop")
            if op in (OP_READ, OP_WRRD):
                for _ in range(ln):
                    await self.pulse("d_rd_push", d_rd_data=self.reads.pop(0) if self.reads else 0xEE)
            if self.hang:
                continue
            await self.pulse("d_done", d_nack=int(self.nack))

    async def pulse(self, name, **extra):
        d = self.dut
        await RisingEdge(d.clk)
        for k, v in extra.items():
            getattr(d, k).value = v
        getattr(d, name).value = 1
        await RisingEdge(d.clk)
        getattr(d, name).value = 0
        for k in extra:
            getattr(d, k).value = 0

    async def private_write(self, *data, end=True):
        await self.pulse("h_frame_start", h_frame_rd=0)
        for b in data:
            await self.pulse("h_rx_valid", h_rx_data=b)
        if end:
            await self.pulse("h_frame_end")

    async def wait_state(self, st, limit=200):
        for _ in range(limit):
            await FallingEdge(self.dut.clk)
            if int(self.dut.state.value) == st:
                return
        raise AssertionError(f"state {int(self.dut.state.value)} never reached {st}")

    async def private_read(self, n):
        """Take bytes like the I3C target: stop after the one flagged last."""
        d, out = self.dut, []
        await self.pulse("h_frame_start", h_frame_rd=1)
        for _ in range(n):
            await FallingEdge(d.clk)
            out.append((int(d.h_tx_data.value), int(d.h_tx_last.value)))
            await self.pulse("h_tx_take")
        await self.pulse("h_frame_end")
        return out


@cocotb.test()
async def test_write_returns_status(dut):
    env = await Env(dut).setup()
    await env.private_write(cmd(OP_WRITE, 2), 0x48, 0x01, 0x60)
    await env.wait_state(S_RESPOND)
    assert env.starts == [(OP_WRITE, 2, 0x48)] and env.writes == [0x01, 0x60]
    assert int(dut.irq.value) == 1 and int(dut.can_read.value) == 1
    assert await env.private_read(1) == [(0x00, 1)]
    await env.wait_state(S_IDLE, limit=5)
    assert int(dut.irq.value) == 0


@cocotb.test()
async def test_read_and_write_then_read_flag_last_byte(dut):
    env = await Env(dut).setup()
    env.reads = [0xAA, 0xBB, 0xCC]
    await env.private_write(cmd(OP_READ, 3), 0x48)
    await env.wait_state(S_RESPOND)
    assert await env.private_read(3) == [(0xAA, 0), (0xBB, 0), (0xCC, 1)]
    env.reads = [0x19, 0x80]
    await env.private_write(0x81, 0x48, 0x00)  # the plan's example
    await env.wait_state(S_RESPOND)
    assert env.starts[-1] == (OP_WRRD, 2, 0x48) and env.writes == [0x00]
    assert await env.private_read(2) == [(0x19, 0), (0x80, 1)]


@cocotb.test()
async def test_status_skips_device_and_busy_blocks_writes(dut):
    env = await Env(dut).setup()
    await env.private_write(cmd(OP_STATUS), 0x00)
    await env.wait_state(S_RESPOND)
    assert env.starts == []
    assert await env.private_read(1) == [(0x00, 1)]
    env.hang = True
    await env.private_write(cmd(OP_READ, 1), 0x48)
    await env.wait_state(S_EXEC)
    assert int(dut.busy.value) == 1 and int(dut.can_write.value) == 0 and int(dut.can_read.value) == 0


@cocotb.test()
async def test_frame_end_drops_partial_command(dut):
    env = await Env(dut).setup()
    await env.private_write(cmd(OP_WRITE, 2))
    await FallingEdge(dut.clk)
    assert int(dut.state.value) == S_IDLE
    await env.private_write(cmd(OP_WRITE, 2), 0x48, 0x01)
    await FallingEdge(dut.clk)
    assert int(dut.state.value) == S_IDLE and env.starts == []


@cocotb.test()
async def test_take_outside_read_ignored_and_new_write_drops_response(dut):
    env = await Env(dut).setup()
    env.reads = [0x0A, 0x0B]
    await env.private_write(cmd(OP_READ, 2), 0x48)
    await env.wait_state(S_RESPOND)
    await env.pulse("h_tx_take")  # not inside a private read: ignored
    await FallingEdge(dut.clk)
    assert int(dut.h_tx_data.value) == 0x0A
    await env.private_write(cmd(OP_STATUS), 0x00, end=False)  # new command drops the response
    await env.wait_state(S_RESPOND)
    await env.pulse("h_frame_end")
    assert await env.private_read(1) == [(0x00, 1)]


@cocotb.test()
async def test_error_flags(dut):
    env = await Env(dut).setup()
    env.nack = True
    await env.private_write(cmd(OP_WRITE, 1), 0x49, 0x00)
    await env.wait_state(S_RESPOND)
    assert (await env.private_read(1))[0][0] == NACK and int(dut.err.value) == 1
    env.nack = False
    await env.pulse("par_err")
    await env.private_write(cmd(OP_STATUS), 0x00)
    await env.wait_state(S_RESPOND)
    assert (await env.private_read(1))[0][0] == NACK | PARITY  # status keeps the flags
    await env.private_write(cmd(OP_WRITE, 1), 0x48, 0x00)
    await env.wait_state(S_RESPOND)
    assert (await env.private_read(1))[0][0] == 0x00 and int(dut.err.value) == 0


@cocotb.test()
async def test_exec_timeout_aborts(dut):
    env = await Env(dut).setup(limit=500)
    env.hang = True
    await env.private_write(cmd(OP_READ, 2), 0x48)
    await env.wait_state(S_RESPOND, limit=1000)
    assert env.aborts == 1 and env.bus_timeouts == 0
    assert await env.private_read(2) == [(0xEE, 0), (0xEE, 1)]  # what arrived before the stall
    await env.private_write(cmd(OP_STATUS), 0x00)
    await env.wait_state(S_RESPOND)
    assert (await env.private_read(1))[0][0] == TIMEOUT


@cocotb.test()
async def test_bus_stall_timeout(dut):
    env = await Env(dut).setup(limit=300)
    d = dut
    await RisingEdge(d.clk)
    d.bus_active.value = 1
    for _ in range(10):  # SCL edges keep it alive
        await ClockCycles(d.clk, 200)
        await env.pulse("bus_kick")
    assert env.bus_timeouts == 0
    await ClockCycles(d.clk, 400)  # SCL stops
    assert env.bus_timeouts == 1
    d.bus_active.value = 0
    await ClockCycles(d.clk, 400)
    assert env.bus_timeouts == 1 and env.aborts == 0
    assert int(d.err.value) == 0  # not a status flag
