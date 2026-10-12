# SPDX-License-Identifier: Apache-2.0
"""MIPI I3C SDR controller for the Track B bridge, in plain Python.

The same file runs under MicroPython on the demo board's RP2 and under CPython in
the cocotb simulation (test/unit/test_firmware.py), so these frames are the ones
checked against the RTL. It follows test/models/i3c_controller.py bit for bit.

The bus is described in slots. One slot is a quarter of an SCL period and holds an
SCL level and an SDA state: driven low (L), driven high (H) or released (Z).
Open-drain phases use L and Z, push-pull phases use L and H. A player (players.py
or pio_player.py on the board, the simulator in the tests) plays a list of slots
and returns SDA as sampled in the middle of each one.

Per bit: SDA changes a quarter period after SCL falls and SCL is high for half a
period. Read bits are taken from the last low slot, while the target still drives
them. Writes are queued and played in one burst; every read plays the queue.
"""

L, H, Z = 0, 1, 2  # SDA states; a slot is (scl << 2) | sda

BROADCAST = 0x7E
CCC_ENTDAA = 0x07
CCC_RSTDAA = 0x06
CCC_SETDASA = 0x87
CCC_ENTHDR0 = 0x20


def odd_parity(value, bits):
    """Parity bit that makes the total number of ones (value + bit) odd."""
    return 1 - (bin(value & ((1 << bits) - 1)).count("1") & 1)


def split_bursts(slots, limit):
    """Cut a slot list into bursts of at most `limit` slots, for players that can
    only play that many back to back. A burst ends on a slot with SCL low whenever
    its second half has one, so the pause between bursts stretches a low phase."""
    out = []
    i = 0
    while len(slots) - i > limit:
        k = i + limit
        while k > i + limit // 2 and slots[k - 1] >> 2:
            k -= 1
        if k == i + limit // 2:
            k = i + limit
        out.append(slots[i:k])
        i = k
    out.append(slots[i:])
    return out


class SlotBus:
    """Builds bus conditions and bits out of slots and plays them on a player."""

    def __init__(self, player):
        self.player = player
        self.scl = 1       # idle bus: SCL high, SDA released
        self.sda = Z
        self.open = False  # between START and STOP
        self.q = []
        self.marks = []    # slots whose sample the caller wants

    # ------------------------------------------------------------ slots
    def _slot(self, scl, sda=None):
        if sda is not None:
            self.sda = sda
        self.scl = scl
        self.q.append((scl << 2) | self.sda)

    def _mark(self):
        self.marks.append(len(self.q) - 1)

    def flush(self):
        """Play the queued slots; return the samples that were marked.
        Mid-transfer the bus is parked with SCL low, so the pause that follows
        (a decision in Python) only stretches a low phase."""
        if not self.q:
            return []
        if self.open and self.scl:
            self._slot(0)
        samples = self.player.run(self.q)
        out = [samples[i] for i in self.marks]
        self.q = []
        self.marks = []
        return out

    def wait_us(self, us):
        self.flush()
        self.player.wait_us(us)

    # ------------------------------------------------------------ bus conditions
    def start(self):
        """START from the idle bus."""
        self.open = True
        self._slot(1, L)
        self._slot(1)

    def rstart(self):
        """Repeated START from SCL low."""
        self._slot(0)
        self._slot(0, Z)
        self._slot(1)
        self._slot(1, L)

    def stop(self):
        """STOP from SCL low; leaves the bus idle."""
        self._slot(0)
        self._slot(0, L)
        self._slot(1)
        self._slot(1, Z)
        self._slot(1)
        self.open = False
        self.flush()

    # ------------------------------------------------------------ bits and bytes
    def write_bit(self, bit, pp=True):
        self._slot(0)
        self._slot(0, (H if bit else L) if pp else (Z if bit else L))
        self._slot(1)
        self._slot(1)

    def _read_slots(self):
        self._slot(0, Z)
        self._slot(0)
        self._mark()
        self._slot(1)
        self._slot(1)

    def read_bit(self):
        self._read_slots()
        return self.flush()[-1]

    def read_bits(self, n):
        """n released bits in one burst, MSB first."""
        for _ in range(n):
            self._read_slots()
        v = 0
        for b in self.flush()[-n:]:
            v = (v << 1) | b
        return v

    def write_byte(self, b, pp=True, parity=True):
        """8 data bits, then the odd-parity T-bit (unless parity=False)."""
        for i in range(7, -1, -1):
            self.write_bit((b >> i) & 1, pp)
        if parity:
            self.write_bit(odd_parity(b, 8), pp)

    def header(self, addr, rnw, od=True):
        """7-bit address + R/W, then the ACK bit. Returns True on ACK.
        Open-drain after START (arbitration); push-pull is allowed after Sr."""
        self.write_byte((addr << 1) | rnw, pp=not od, parity=False)
        return self.read_bit() == 0

    def read_t(self, abort=False):
        """T-bit of a read (End-of-Data). Returns the T value sent by the target.
        T=0: the target ends; the controller takes SDA low to finish with P or Sr.
        T=1 and abort: the controller pulls SDA low while SCL is high (Sr)."""
        self._slot(0, Z)
        self._slot(0)
        self._mark()
        t = self.flush()[-1]
        if t == 0:
            self._slot(1, L)  # take over SDA as the target lets go
            self._slot(1)
        elif abort:
            self._slot(1)     # let the target release first
            self._slot(1, L)  # SDA falls while SCL is high: repeated START
        else:
            self._slot(1)
            self._slot(1)
        return t


class I3CController:
    """Frames a controller sends to the bridge. Every method leaves the bus idle
    unless it says otherwise."""

    def __init__(self, player):
        self.bus = SlotBus(player)

    # ------------------------------------------------------------ transfers
    def private_write(self, da, data, use_7e=False):
        """S, [7E/W, Sr,] DA/W, data + T..., P. Returns True if DA was ACKed."""
        bus = self.bus
        bus.start()
        if use_7e:
            bus.header(BROADCAST, 0)
            bus.rstart()
            ack = bus.header(da, 0, od=False)
        else:
            ack = bus.header(da, 0)
        if ack:
            for b in data:
                bus.write_byte(b)
        bus.stop()
        return ack

    def private_read(self, da, max_len=16, use_7e=False):
        """S, [7E/W, Sr,] DA/R, bytes until T=0 (or max_len, then abort), P.
        Returns the bytes, or None if the target NACKed (for example while busy)."""
        bus = self.bus
        bus.start()
        if use_7e:
            bus.header(BROADCAST, 0)
            bus.rstart()
            ack = bus.header(da, 1, od=False)
        else:
            ack = bus.header(da, 1)
        if not ack:
            bus.stop()
            return None
        out = []
        while True:
            out.append(bus.read_bits(8))
            t = bus.read_t(abort=len(out) >= max_len)
            if t == 0 or len(out) >= max_len:
                break
        bus.stop()
        return out

    def ccc_broadcast(self, code, payload=(), stop=True):
        """S, 7E/W, CCC + T, payload + T..., [P]. Returns True if 7E was ACKed."""
        bus = self.bus
        bus.start()
        ack = bus.header(BROADCAST, 0)
        bus.write_byte(code)
        for b in payload:
            bus.write_byte(b)
        if stop:
            bus.stop()
        else:
            bus.flush()
        return ack

    def rstdaa(self):
        return self.ccc_broadcast(CCC_RSTDAA)

    def setdasa(self, sa, da):
        """S, 7E/W, SETDASA + T, Sr, SA/W, {DA, 0} + T, P. Returns True if SA was
        ACKed (the bridge does not support SETDASA and NACKs)."""
        bus = self.bus
        bus.start()
        bus.header(BROADCAST, 0)
        bus.write_byte(CCC_SETDASA)
        bus.rstart()
        ack = bus.header(sa, 0, od=False)
        if ack:
            bus.write_byte(da << 1)
        bus.stop()
        return ack

    def entdaa(self, das):
        """Dynamic address assignment. Offers each address in das to the next target
        that answers 7E/R. Returns [(pid, bcr, dcr, da, acked)] per target found."""
        bus = self.bus
        found = []
        bus.start()
        bus.header(BROADCAST, 0)
        bus.write_byte(CCC_ENTDAA)
        everyone = True
        for da in das:
            bus.rstart()
            if not bus.header(BROADCAST, 1):
                everyone = False  # no target left without an address
                break
            bits = bus.read_bits(64)  # PID[47:0], BCR, DCR; open-drain, lowest ID wins
            bus.write_byte((da << 1) | odd_parity(da, 7), pp=False, parity=False)
            acked = bus.read_bit() == 0
            found.append((bits >> 16, (bits >> 8) & 0xFF, bits & 0xFF, da, acked))
        if everyone:
            bus.rstart()
            bus.header(BROADCAST, 1)  # expect NACK: everyone has an address
        bus.stop()
        return found

    # ------------------------------------------------------------ HDR
    def enthdr(self, mode=0):
        """ENTHDRx with no STOP: the bus is now in HDR mode."""
        return self.ccc_broadcast(CCC_ENTHDR0 | mode, stop=False)

    def hdr_traffic(self, n_edges, getrandbits=None):
        """HDR-DDR-like traffic: SCL toggles and SDA may change once per SCL phase,
        including while SCL is high (which looks like fake START/STOP to SDR logic).
        One SDA change per low phase can never form the 4-pulse exit pattern."""
        if getrandbits is None:
            import random
            getrandbits = random.getrandbits
        bus = self.bus
        for _ in range(n_edges):
            bus._slot(bus.scl, H if getrandbits(1) else L)
            bus._slot(1 - bus.scl)
        bus._slot(0)
        bus.flush()

    def hdr_exit(self, pulses=4, then_stop=True):
        """HDR Exit Pattern: SCL held low while SDA pulses `pulses` times, then STOP.
        Starts with a clean SCL pulse (SDA steady high) so earlier traffic in the
        same low phase cannot add to the count."""
        bus = self.bus
        bus._slot(0, H)
        bus._slot(1)
        bus._slot(0)
        for _ in range(pulses):
            bus._slot(0, L)
            bus._slot(0, H)
        if then_stop:
            bus._slot(0, L)
            bus._slot(1)
            bus._slot(1, Z)  # SDA rises while SCL is high: STOP
            bus._slot(1)
            bus.open = False
        bus.flush()
