# SPDX-License-Identifier: Apache-2.0
"""Bring-up checklist for the bridge: FPGA dry run now, silicon later.

run_all() walks the steps of the plan (section 15) and prints one PASS / FAIL
line per check. It needs a board (boards.py: reset, ui_in, uo_out) and a player
(players.py). The simulation runs the same function against the RTL
(test/unit/test_firmware.py), so a FAIL on hardware points at the hardware
set-up or the chip, not at this script.

Nothing here needs an I2C device. With a sensor on the downstream bus (default
address 0x48) step 4 also reads two bytes from its register 0.
"""
from .bridge import NACK, OP_READ, OP_WRITE, PARITY, Bridge, BridgeError, cmd, status_text
from .i3c import Z, I3CController, odd_parity

# uo_out
STATE, DA_VALID, IRQ, BUSY, ERR = 0x0F, 0x10, 0x20, 0x40, 0x80
S_IDLE, S_HDR = 0, 8
I2C_FAST = 0x08  # ui_in[3]


class Report:
    def __init__(self, out=print):
        self.out = out
        self.results = []  # (name, ok, detail)

    def check(self, name, ok, detail=""):
        self.results.append((name, bool(ok), detail))
        self.out("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" - " + detail) if detail else ""))
        return bool(ok)

    def info(self, text):
        self.out("       " + text)

    def step(self, title):
        self.out("")
        self.out("== " + title)

    @property
    def failed(self):
        return [r for r in self.results if not r[1]]


class _Pins:
    """uo_out checks; skipped (and counted as passed) when the board cannot read uo_out."""

    def __init__(self, board, report):
        self.board = board
        self.r = report

    def read(self):
        return self.board.uo()

    def check(self, name, mask, value):
        v = self.board.uo()
        if v is None:
            self.r.info(name + ": uo_out not wired, not checked")
            return True
        return self.r.check(name, (v & mask) == value, "uo_out = 0x%02X" % v)


def _hex(data):
    return " ".join("%02X" % b for b in data)


def run_all(board, player, da=0x09, sensor=0x48, expect=None, inst=2, i2c_fast=False, hdr_edges=200,
            out=print):
    """Run every step. Returns the Report; report.failed is empty when all passed.

    da      dynamic address to assign (any free 7-bit address from 0x08 to 0x3D)
    sensor  downstream I2C address to try in step 4
    expect  bytes that register 0 of the sensor must return (the simulation sets this)
    inst    value for the two PID instance pins, ui_in[2:1]
    """
    r = Report(out)
    pins = _Pins(board, r)
    i3c = I3CController(player)
    br = Bridge(i3c, da)

    # ------------------------------------------------------------ 1. reset state
    r.step("1. Reset state")
    board.set_ui((inst << 1) | (I2C_FAST if i2c_fast else 0))
    board.reset()
    pins.check("after reset every status output is low", 0xFF, 0x00)
    r.check("I3C SDA is released and pulled high", player.run([(1 << 2) | Z])[0] == 1,
            "if this fails, check the SDA pull-up")

    # ------------------------------------------------------------ 2. dynamic address
    r.step("2. Dynamic address assignment")
    try:
        found = i3c.entdaa([da])
        ok = r.check("ENTDAA finds one target and it ACKs the address", len(found) == 1 and found[0][4],
                     "%d found" % len(found))
        if ok:
            pid, bcr, dcr = found[0][0], found[0][1], found[0][2]
            r.info("PID 0x%012X  BCR 0x%02X  DCR 0x%02X  DA 0x%02X" % (pid, bcr, dcr, da))
            r.check("PID: manufacturer 0x7FFF, fixed type, part 0x0001",
                    (pid >> 33) == 0x7FFF and ((pid >> 32) & 1) == 0 and ((pid >> 16) & 0xFFFF) == 0x0001)
            r.check("PID instance matches ui_in[2:1]", ((pid >> 12) & 0xF) == inst and (pid & 0xFFF) == 0,
                    "instance %d" % ((pid >> 12) & 0xF))
            r.check("BCR = 0x01, DCR = 0x00", bcr == 0x01 and dcr == 0x00)
        pins.check("DA_VALID is high", DA_VALID, DA_VALID)
        r.check("a target that has an address does not answer ENTDAA", i3c.entdaa([da + 1]) == [])
        r.check("RSTDAA is ACKed", i3c.rstdaa())
        pins.check("DA_VALID is low after RSTDAA", DA_VALID, 0)
        r.check("the old address is not answered any more", i3c.private_read(da) is None)
        r.check("SETDASA is NACKed (not supported)", not i3c.setdasa(0x3A, da))
        found = i3c.entdaa([da])
        r.check("ENTDAA works again after RSTDAA", len(found) == 1 and found[0][4])
        pins.check("DA_VALID is high again", DA_VALID, DA_VALID)
    except BridgeError as e:
        r.check("dynamic address assignment", False, str(e))

    # ------------------------------------------------------------ 3. status round trip
    r.step("3. Status command (nothing needed on the I2C side)")
    try:
        st = br.status()
        r.check("status round trip returns 0x00", st == 0x00, status_text(st))
        r.check("the 7E-prefixed form of private transfers works",
                i3c.private_write(da, [cmd(3), 0], use_7e=True) and i3c.private_read(da, use_7e=True) == [0x00])
    except BridgeError as e:
        r.check("status round trip", False, str(e))

    # ------------------------------------------------------------ 4. downstream I2C
    r.step("4. Downstream I2C (device at 0x%02X if present)" % sensor)
    present = False
    try:
        data = br.write_read(sensor, 0x00, 2)
        st = br.status()
        present = not st & NACK
        if present:
            r.check("bridged read of 2 bytes from register 0", expect is None or data == list(expect),
                    "data " + _hex(data))
            raw = (data[0] << 8) | data[1]
            r.info("as a 16-bit temperature register (LM75 / TMP102 style): %.2f C" %
                   ((raw - 65536 if raw & 0x8000 else raw) / 256.0))
            pins.check("ERR is low after a good transfer", ERR, 0)
            st = br.write(sensor, [0x00])  # sets the register pointer: harmless
            r.check("bridged write is acknowledged", st == 0x00, status_text(st))
            again = br.read(sensor, 2)
            r.check("plain read returns the same register", expect is None or again == list(expect),
                    "data " + _hex(again))
        else:
            r.info("no device answered at 0x%02X: checking the NACK path instead" % sensor)
            r.check("a NACKed read is padded with zeros and sets the NACK flag", data == [0, 0] and st == NACK,
                    "data %s, status %s" % (_hex(data), status_text(st)))
            pins.check("ERR is high", ERR, ERR)
            st = br.write(sensor, [0x00])
            r.check("a NACKed write reports NACK and the unsent byte", st == (NACK | 1), status_text(st))
    except BridgeError as e:
        r.check("downstream I2C", False, str(e))

    # ------------------------------------------------------------ 5. HDR
    r.step("5. HDR entry and exit")
    try:
        before = br.status()
        i3c.enthdr(0)
        pins.check("ENTHDR0 puts the target in HDR (state 8)", STATE, S_HDR)
        i3c.hdr_traffic(hdr_edges)
        pins.check("it stays there through %d edges of HDR traffic" % hdr_edges, STATE, S_HDR)
        i3c.hdr_exit()
        pins.check("the exit pattern returns it to IDLE with its address", STATE | DA_VALID, S_IDLE | DA_VALID)
        st = br.status()
        r.check("the bridge still answers", st == before, status_text(st))
    except BridgeError as e:
        r.check("HDR entry and exit", False, str(e))

    # ------------------------------------------------------------ 6. errors
    r.step("6. Parity error and aborted read")
    try:
        bus = i3c.bus
        bus.start()
        ack = bus.header(da, 0)
        bus.write_byte(cmd(OP_WRITE, 1))
        bus.write_byte(sensor)
        bus.write_byte(0x07, parity=False)
        bus.write_bit(1 - odd_parity(0x07, 8))  # wrong T-bit
        bus.stop()
        r.check("the write with a bad T-bit was ACKed at the address", ack)
        pins.check("ERR is high and the target is back in IDLE", ERR | STATE, ERR | S_IDLE)
        st = br.status()
        r.check("status shows the parity error", st & PARITY, status_text(st))

        # A 2-byte read; the controller stops it after the first byte.
        r.check("next command accepted", i3c.private_write(da, [cmd(OP_READ, 2), sensor]))
        first = None
        for _ in range(br.polls):
            first = i3c.private_read(da, max_len=1)
            if first is not None:
                break
            bus.wait_us(br.poll_us)
        r.check("read aborted by the controller after 1 byte", first is not None and len(first) == 1)
        pins.check("the rest of the response is dropped (IRQ low, IDLE)", IRQ | STATE, S_IDLE)
        st = br.status()
        r.check("a new command clears the parity flag", not st & PARITY, status_text(st))
        r.check("the downstream NACK flag matches step 4", bool(st & NACK) == (not present), status_text(st))
    except BridgeError as e:
        r.check("parity error and aborted read", False, str(e))

    r.out("")
    r.out("%d checks, %d failed" % (len(r.results), len(r.failed)))
    return r


def sweep(make_player, da, rates=(100_000, 200_000, 400_000, 600_000, 800_000, 1_000_000, 1_250_000, 1_500_000,
                                 2_000_000), rounds=20, out=print):
    """Step 7 of the plan: find the highest I3C SCL rate that still works.
    make_player(scl_hz) returns a timing-accurate player (pio_player.PioPlayer).
    The bridge must already have its dynamic address. Returns {rate: good rounds}."""
    result = {}
    for hz in rates:
        br = Bridge(I3CController(make_player(hz)), da, polls=50)
        good = 0
        for _ in range(rounds):
            try:
                good += br.status() & ~NACK == 0
            except BridgeError:
                pass
        result[hz] = good
        out("%8d Hz: %d / %d status round trips" % (hz, good, rounds))
    return result
