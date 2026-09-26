# SPDX-License-Identifier: Apache-2.0
"""Bit-level MIPI I3C SDR controller model for cocotb tests (Track B).

Drives SCL push-pull and SDA either open-drain (address header after START, ACK,
ENTDAA) or push-pull (data and T-bits). Every bit operation starts and ends with
SCL low; the idle bus has SCL high and SDA released (pulled up).

Per bit: SDA changes a quarter period after SCL falls, SCL is high for half a
period. Read bits are sampled just before SCL rises, while the target still
drives them; the target hands SDA back on the rising edge of a read T-bit.

Protocol references: MIPI I3C Basic v1.2; Microchip TB3340 (ENTDAA frame,
End-of-Data, HDR exit). Check frames against the spec when the RTL lands.
"""
from cocotb.triggers import Timer

BROADCAST = 0x7E
CCC_ENTDAA = 0x07
CCC_RSTDAA = 0x06
CCC_SETDASA = 0x87
CCC_ENTHDR0 = 0x20


def odd_parity(value, bits):
    """Parity bit that makes the total number of ones (value + bit) odd."""
    return 1 - (bin(value & ((1 << bits) - 1)).count("1") & 1)


class I3CController:
    def __init__(self, scl, sda_oe, sda_out, sda, period_ns=1000):
        self.scl = scl
        self.sda_oe = sda_oe
        self.sda_out = sda_out
        self.sda = sda
        self.q = period_ns / 4  # quarter bit period
        self.idle()

    # ------------------------------------------------------------ drivers
    def idle(self):
        self.scl.value = 1
        self._release()

    async def _w(self, n=1):
        await Timer(self.q * n, unit="ns")

    def _release(self):
        self.sda_oe.value = 0
        self.sda_out.value = 0

    def _od(self, bit):
        """Open-drain: pull low for 0, release for 1."""
        self.sda_out.value = 0
        self.sda_oe.value = 0 if bit else 1

    def _pp(self, bit):
        """Push-pull: drive the bit."""
        self.sda_out.value = bit
        self.sda_oe.value = 1

    def _bus(self):
        return int(self.sda.value)

    # ------------------------------------------------------------ bus conditions
    async def start(self):
        """START from the idle bus."""
        self._od(0)
        await self._w(2)
        self.scl.value = 0

    async def rstart(self):
        """Repeated START from SCL low."""
        await self._w()
        self._release()
        await self._w()
        self.scl.value = 1
        await self._w()
        self._od(0)
        await self._w()
        self.scl.value = 0

    async def stop(self):
        """STOP from SCL low; leaves the bus idle."""
        await self._w()
        self._od(0)
        await self._w()
        self.scl.value = 1
        await self._w()
        self._release()
        await self._w(2)

    # ------------------------------------------------------------ bits and bytes
    async def write_bit(self, bit, pp=True):
        await self._w()
        (self._pp if pp else self._od)(bit)
        await self._w()
        self.scl.value = 1
        await self._w(2)
        self.scl.value = 0

    async def read_bit(self):
        self._release()
        await self._w(2)
        v = self._bus()
        self.scl.value = 1
        await self._w(2)
        self.scl.value = 0
        return v

    async def write_byte(self, b, pp=True, parity=True):
        """8 data bits, then the odd-parity T-bit (unless parity=False)."""
        for i in range(7, -1, -1):
            await self.write_bit((b >> i) & 1, pp)
        if parity:
            await self.write_bit(odd_parity(b, 8), pp)

    async def header(self, addr, rnw, od=True):
        """7-bit address + R/W, then the ACK bit. Returns True on ACK.
        Open-drain after START (arbitration); push-pull is allowed after Sr."""
        await self.write_byte((addr << 1) | rnw, pp=not od, parity=False)
        return (await self.read_bit()) == 0

    async def read_byte(self):
        v = 0
        for _ in range(8):
            v = (v << 1) | await self.read_bit()
        return v

    async def read_t(self, abort=False):
        """T-bit of a read (End-of-Data). Returns the target's T value.
        T=0: the target ends; the controller takes SDA low to finish with P or Sr.
        T=1 and abort: the controller pulls SDA low while SCL is high (Sr)."""
        self._release()
        await self._w(2)
        t = self._bus()
        self.scl.value = 1
        if t == 0:
            self._od(0)  # take over SDA as the target lets go
            await self._w(2)
        elif abort:
            await self._w()  # let the target release first
            self._od(0)      # SDA falls while SCL high: repeated START
            await self._w()
        else:
            await self._w(2)
        self.scl.value = 0
        return t

    # ------------------------------------------------------------ transfers
    async def private_write(self, da, data, use_7e=False):
        """S, [7E/W, Sr,] DA/W, data + T..., P. Returns True if DA was ACKed."""
        await self.start()
        if use_7e:
            await self.header(BROADCAST, 0)
            await self.rstart()
            ack = await self.header(da, 0, od=False)
        else:
            ack = await self.header(da, 0)
        if ack:
            for b in data:
                await self.write_byte(b)
        await self.stop()
        return ack

    async def private_read(self, da, max_len=16, use_7e=False):
        """S, [7E/W, Sr,] DA/R, bytes until T=0 (or max_len, then abort), P.
        Returns the bytes, or None if the target NACKed (for example while busy)."""
        await self.start()
        if use_7e:
            await self.header(BROADCAST, 0)
            await self.rstart()
            ack = await self.header(da, 1, od=False)
        else:
            ack = await self.header(da, 1)
        if not ack:
            await self.stop()
            return None
        out = []
        while True:
            out.append(await self.read_byte())
            t = await self.read_t(abort=len(out) >= max_len)
            if t == 0 or len(out) >= max_len:
                break
        await self.stop()
        return out

    async def ccc_broadcast(self, code, payload=(), stop=True):
        """S, 7E/W, CCC + T, payload + T..., [P]. Returns True if 7E was ACKed."""
        await self.start()
        ack = await self.header(BROADCAST, 0)
        await self.write_byte(code)
        for b in payload:
            await self.write_byte(b)
        if stop:
            await self.stop()
        return ack

    async def rstdaa(self):
        return await self.ccc_broadcast(CCC_RSTDAA)

    async def setdasa(self, sa, da):
        """S, 7E/W, SETDASA + T, Sr, SA/W, {DA, 0} + T, P. Returns True if SA was ACKed."""
        await self.start()
        await self.header(BROADCAST, 0)
        await self.write_byte(CCC_SETDASA)
        await self.rstart()
        ack = await self.header(sa, 0, od=False)
        if ack:
            await self.write_byte(da << 1)
        await self.stop()
        return ack

    async def entdaa(self, das):
        """Dynamic address assignment. Offers each address in das to the next target
        that answers 7E/R. Returns [(pid, bcr, dcr, da, acked)] per target found."""
        found = []
        await self.start()
        await self.header(BROADCAST, 0)
        await self.write_byte(CCC_ENTDAA)
        for da in das:
            await self.rstart()
            if not await self.header(BROADCAST, 1):
                break  # no target left without an address
            bits = 0
            for _ in range(64):  # PID[47:0], BCR, DCR; open-drain, lowest ID wins
                bits = (bits << 1) | await self.read_bit()
            await self.write_byte((da << 1) | odd_parity(da, 7), pp=False, parity=False)
            acked = (await self.read_bit()) == 0
            found.append((bits >> 16, (bits >> 8) & 0xFF, bits & 0xFF, da, acked))
        else:
            await self.rstart()
            await self.header(BROADCAST, 1)  # expect NACK: everyone has an address
        await self.stop()
        return found

    # ------------------------------------------------------------ HDR
    async def enthdr(self, mode=0):
        """ENTHDRx with no STOP: the bus is now in HDR mode."""
        await self.ccc_broadcast(CCC_ENTHDR0 | mode, stop=False)

    async def hdr_traffic(self, n_edges, rng):
        """HDR-DDR-like traffic: SCL toggles and SDA may change once per SCL phase,
        including while SCL is high (which looks like fake START/STOP to SDR logic).
        One SDA change per low phase can never form the 4-pulse exit pattern."""
        for _ in range(n_edges):
            self._pp(rng.getrandbits(1))
            await self._w()
            self.scl.value = 1 - int(self.scl.value)
            await self._w()
        self.scl.value = 0
        await self._w()

    async def hdr_exit(self, pulses=4, then_stop=True):
        """HDR Exit Pattern: SCL held low while SDA pulses `pulses` times, then STOP.
        Starts with a clean SCL pulse (SDA steady high) so earlier traffic in the
        same low phase cannot add to the count."""
        self._pp(1)
        await self._w()
        self.scl.value = 1
        await self._w()
        self.scl.value = 0
        await self._w()
        for _ in range(pulses):
            self._pp(0)
            await self._w()
            self._pp(1)
            await self._w()
        if then_stop:
            self._pp(0)
            await self._w()
            self.scl.value = 1
            await self._w()
            self._release()  # SDA rises while SCL is high: STOP
            await self._w(2)
