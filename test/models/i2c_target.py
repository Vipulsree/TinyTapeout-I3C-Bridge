# SPDX-License-Identifier: Apache-2.0
"""Behavioural I2C target (a sensor with a register file) for cocotb tests.

It watches the resolved SCL/SDA wires and only ever pulls SDA low (open-drain).
Protocol: the first byte of a write sets the register pointer, later bytes are
stored at the pointer (auto-increment); reads return bytes from the pointer.
"""
import cocotb
from cocotb.triggers import FallingEdge, First, RisingEdge


class I2CTarget:
    def __init__(self, scl, sda, sda_pull, address=0x48, size=256):
        self.scl = scl
        self.sda = sda
        self.sda_pull = sda_pull
        self.address = address
        self.regs = bytearray(size)
        self.ptr = 0
        self.present = True  # False: NACK the address, like an unplugged sensor
        self.log = []  # one ["W" | "R", [bytes]] entry per acknowledged transfer
        self._task = None

    def start(self):
        self.sda_pull.value = 0
        self._task = cocotb.start_soon(self._run())
        return self

    def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.sda_pull.value = 0

    # ------------------------------------------------------------ internals
    def _pull(self, low):
        self.sda_pull.value = 1 if low else 0

    def _drive_bit(self, bit):
        self._pull(bit == 0)

    def _next_read(self, entry):
        b = self.regs[self.ptr]
        self.ptr = (self.ptr + 1) % len(self.regs)
        entry[1].append(b)
        return b

    def _write(self, b, entry):
        if not entry[1]:
            self.ptr = b % len(self.regs)  # first data byte = register pointer
        else:
            self.regs[self.ptr] = b
            self.ptr = (self.ptr + 1) % len(self.regs)
        entry[1].append(b)

    async def _run(self):
        phase = "idle"
        shift = n = 0
        is_addr = rw = acked = master_ack = False
        tx = 0
        entry = None
        while True:
            r_scl, f_scl = RisingEdge(self.scl), FallingEdge(self.scl)
            r_sda, f_sda = RisingEdge(self.sda), FallingEdge(self.sda)
            t = await First(r_scl, f_scl, r_sda, f_sda)
            scl_high = int(self.scl.value) == 1

            if t is f_sda and scl_high:  # START or repeated START
                self._pull(False)
                phase, is_addr, shift, n, entry = "rx", True, 0, 0, None
                continue
            if t is r_sda and scl_high:  # STOP
                self._pull(False)
                phase, entry = "idle", None
                continue
            if phase in ("idle", "wait"):
                continue

            if t is r_scl:  # the controller samples on the rising edge
                bit = int(self.sda.value)
                if phase == "rx":
                    shift = ((shift << 1) | bit) & 0xFF
                    n += 1
                elif phase == "tx":
                    n += 1
                elif phase == "tx_ack":
                    master_ack = bit == 0

            elif t is f_scl:  # the target changes SDA while SCL is low
                if phase == "rx" and n == 8:
                    if is_addr:
                        rw = bool(shift & 1)
                        acked = (shift >> 1) == self.address and self.present
                        if acked:
                            entry = ["R" if rw else "W", []]
                            self.log.append(entry)
                    else:
                        acked = True
                        self._write(shift, entry)
                    self._pull(acked)
                    phase = "rx_ack"
                elif phase == "rx_ack":
                    self._pull(False)
                    if not acked:
                        phase = "wait"
                    elif is_addr and rw:
                        is_addr, n = False, 0
                        tx = self._next_read(entry)
                        self._drive_bit(tx >> 7)
                        phase = "tx"
                    else:
                        is_addr, shift, n = False, 0, 0
                        phase = "rx"
                elif phase == "tx":
                    if n < 8:
                        self._drive_bit((tx >> (7 - n)) & 1)
                    else:
                        self._pull(False)  # release for the controller's ACK/NACK
                        phase = "tx_ack"
                elif phase == "tx_ack":
                    if master_ack:
                        n = 0
                        tx = self._next_read(entry)
                        self._drive_bit(tx >> 7)
                        phase = "tx"
                    else:
                        phase = "wait"
