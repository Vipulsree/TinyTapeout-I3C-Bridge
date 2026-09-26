# SPDX-License-Identifier: Apache-2.0
"""Bit-banged I2C controller for cocotb tests (drives the bus only by pulling low).

Used as the external host in modes 100/101 and to check the I2C target model.
Honours clock stretching: after releasing SCL it waits until the line is high.
"""
from cocotb.triggers import Timer


class I2CController:
    def __init__(self, scl_pull, sda_pull, scl, sda, period_ns=10_000):
        self.scl_pull = scl_pull
        self.sda_pull = sda_pull
        self.scl = scl
        self.sda = sda
        self.q = period_ns / 4  # quarter bit period
        scl_pull.value = 0
        sda_pull.value = 0

    async def _w(self, n=1):
        await Timer(self.q * n, unit="ns")

    def _scl_low(self, low):
        self.scl_pull.value = 1 if low else 0

    def _sda_bit(self, bit):
        self.sda_pull.value = 0 if bit else 1

    async def _release_scl(self):
        self._scl_low(False)
        while int(self.scl.value) == 0:  # clock stretching
            await Timer(self.q / 4, unit="ns")

    # ------------------------------------------------------------ bit level
    async def start(self):
        """START from idle, or repeated START after a byte (SCL low)."""
        self._sda_bit(1)
        await self._w()
        await self._release_scl()
        await self._w()
        self._sda_bit(0)
        await self._w()
        self._scl_low(True)
        await self._w()

    async def stop(self):
        self._sda_bit(0)
        await self._w()
        await self._release_scl()
        await self._w()
        self._sda_bit(1)
        await self._w(2)

    async def write_bit(self, bit):
        self._sda_bit(bit)
        await self._w()
        await self._release_scl()
        await self._w(2)
        self._scl_low(True)
        await self._w()

    async def read_bit(self):
        self._sda_bit(1)
        await self._w()
        await self._release_scl()
        await self._w()
        v = int(self.sda.value)
        await self._w()
        self._scl_low(True)
        await self._w()
        return v

    async def write_byte(self, b):
        """Send one byte; returns True if the target ACKed."""
        for i in range(7, -1, -1):
            await self.write_bit((b >> i) & 1)
        return (await self.read_bit()) == 0

    async def read_byte(self, ack):
        v = 0
        for _ in range(8):
            v = (v << 1) | await self.read_bit()
        await self.write_bit(0 if ack else 1)
        return v

    # ------------------------------------------------------------ transfers
    async def write(self, addr, data):
        """S, addr+W, data..., P. Returns False on any NACK."""
        await self.start()
        ok = await self.write_byte(addr << 1)
        for b in data:
            if not ok:
                break
            ok = await self.write_byte(b)
        await self.stop()
        return ok

    async def read(self, addr, n):
        """S, addr+R, n bytes, P. Returns None if the address is NACKed."""
        await self.start()
        if not await self.write_byte((addr << 1) | 1):
            await self.stop()
            return None
        out = [await self.read_byte(ack=i < n - 1) for i in range(n)]
        await self.stop()
        return out

    async def write_read(self, addr, wdata, n):
        """S, addr+W, wdata, Sr, addr+R, n bytes, P. Returns None on NACK."""
        await self.start()
        ok = await self.write_byte(addr << 1)
        for b in wdata:
            if not ok:
                break
            ok = await self.write_byte(b)
        if ok:
            await self.start()
            ok = await self.write_byte((addr << 1) | 1)
        if not ok:
            await self.stop()
            return None
        out = [await self.read_byte(ack=i < n - 1) for i in range(n)]
        await self.stop()
        return out
