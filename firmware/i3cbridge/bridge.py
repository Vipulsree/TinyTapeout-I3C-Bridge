# SPDX-License-Identifier: Apache-2.0
"""Host side of the bridge protocol (docs/info.md): a command goes out in a private
write, the answer comes back in a later private read. While the downstream I2C
transfer runs the bridge NACKs its read address, so the read is retried."""

OP_WRITE, OP_READ, OP_WRRD, OP_STATUS = 0, 1, 2, 3

# Status byte
NACK = 0x80     # the I2C device did not acknowledge
PARITY = 0x40   # I3C parity error (TE1 / TE2)
OVF = 0x20      # FIFO overflow
TIMEOUT = 0x10  # 35 ms timeout
COUNT = 0x07    # bytes in the FIFO


def cmd(op, length=1):
    """CMD byte: op in bits 7:6, length - 1 in bits 1:0 (1 to 4 bytes)."""
    if not 1 <= length <= 4:
        raise ValueError("length must be 1 to 4")
    return (op << 6) | (length - 1)


def status_text(s):
    flags = [n for bit, n in ((NACK, "NACK"), (PARITY, "PARITY"), (OVF, "OVERFLOW"), (TIMEOUT, "TIMEOUT")) if s & bit]
    return "0x%02X (%s, FIFO count %d)" % (s, " ".join(flags) or "ok", s & COUNT)


class BridgeError(Exception):
    pass


class Bridge:
    def __init__(self, i3c, da, polls=200, poll_us=500):
        self.i3c = i3c
        self.da = da
        self.polls = polls      # private reads to try before giving up
        self.poll_us = poll_us  # pause between them

    def transact(self, request, max_len=8):
        """Private write with the request, then poll private reads until the bridge
        ACKs. Returns the response bytes."""
        if not self.i3c.private_write(self.da, request):
            raise BridgeError("bridge did not ACK the private write (no address, or busy)")
        for _ in range(self.polls):
            out = self.i3c.private_read(self.da, max_len)
            if out is not None:
                return out
            self.i3c.bus.wait_us(self.poll_us)
        raise BridgeError("bridge never ACKed the private read")

    def status(self):
        """Status byte; does not clear the error flags."""
        return self.transact([cmd(OP_STATUS), 0])[0]

    def write(self, addr, data):
        """I2C write of 1 to 4 bytes. Returns the status byte (0x00 = done)."""
        data = list(data)
        return self.transact([cmd(OP_WRITE, len(data)), addr] + data)[0]

    def read(self, addr, length):
        """I2C read of 1 to 4 bytes. A NACKed read returns zeros: check status()."""
        return self.transact([cmd(OP_READ, length), addr])

    def write_read(self, addr, reg, length):
        """I2C write of one byte (a register pointer), repeated START, read of 1 to 4 bytes."""
        return self.transact([cmd(OP_WRRD, length), addr, reg])

    def scan(self, first=0x08, last=0x77):
        """Addresses that ACK a 1-byte read on the downstream bus."""
        found = []
        for addr in range(first, last + 1):
            self.read(addr, 1)
            if not self.status() & NACK:
                found.append(addr)
        return found
