# SPDX-License-Identifier: Apache-2.0
"""What the bring-up script needs from the hardware around the bridge: reset,
the ui_in pins, the uo_out pins and the GPIO numbers of the I3C bus.

TTDemoBoard  the Tiny Tapeout demo board (ASIC, or the FPGA breakout in its place),
             through the TT MicroPython SDK (ttboard).
PicoBoard    a bare Raspberry Pi Pico wired to any FPGA board with jumper wires.
"""
from machine import PWM, Pin
from time import sleep_ms


class TTDemoBoard:
    def __init__(self, tt=None, clock_hz=25_000_000):
        """tt: the SDK's DemoBoard object (the `tt` of the REPL). The design must
        already be selected: tt.shuttle.<name>.enable()."""
        if tt is None:
            from ttboard.demoboard import DemoBoard
            tt = DemoBoard.get()
        from ttboard.mode import RPMode
        tt.mode = RPMode.ASIC_RP_CONTROL  # the RP2 drives ui_in, clock and reset
        self.tt = tt
        self.scl_gpio = tt.pins.uio2.gpio_num
        self.sda_gpio = tt.pins.uio3.gpio_num
        tt.clock_project_PWM(clock_hz)
        self.i2c_pullups(True)

    def i2c_pullups(self, on):
        """RP2 pull-ups on the downstream I2C lines (uio[6], uio[7]). The SDK's
        default is a pull-down, which would hold an empty bus low. Weak (tens of
        kOhm): fine with nothing connected; a sensor board brings its own."""
        for p in (self.tt.pins.uio6, self.tt.pins.uio7):
            p.pull = Pin.PULL_UP if on else None

    def reset(self, ms=10):
        self.tt.reset_project(True)
        sleep_ms(ms)
        self.tt.reset_project(False)
        sleep_ms(ms)

    def set_ui(self, value):
        self.tt.ui_in.value = value

    def uo(self):
        return int(self.tt.uo_out.value)


class PicoBoard:
    def __init__(self, scl, sda, rst_n=None, uo=None, ui=None, clk=None, clock_hz=25_000_000):
        """GPIO numbers on the Pico. scl / sda go to uio[2] / uio[3] of the design.
        rst_n  GPIO wired to rst_n (None: reset the FPGA by hand when asked)
        uo     list of 8 GPIOs wired to uo_out[0..7] (None: status pins are not checked)
        ui     list of 8 GPIOs wired to ui_in[0..7]; entries may be None (strap those pins on the FPGA)
        clk    GPIO that outputs the 25 MHz clock (None: the FPGA board has its own)"""
        self.scl_gpio = scl
        self.sda_gpio = sda
        self.rst = Pin(rst_n, Pin.OUT, value=1) if rst_n is not None else None
        self.uo_pins = [Pin(g, Pin.IN) for g in uo] if uo else None
        self.ui_pins = [Pin(g, Pin.OUT, value=0) if g is not None else None for g in ui] if ui else None
        if clk is not None:
            self.pwm = PWM(Pin(clk))
            self.pwm.freq(clock_hz)
            self.pwm.duty_u16(32768)

    def reset(self, ms=10):
        if self.rst is None:
            input("Press and release the reset button of the FPGA board, then Enter ")
            return
        self.rst.value(0)
        sleep_ms(ms)
        self.rst.value(1)
        sleep_ms(ms)

    def set_ui(self, value):
        if self.ui_pins:
            for i, p in enumerate(self.ui_pins):
                if p is not None:
                    p.value((value >> i) & 1)

    def uo(self):
        if not self.uo_pins:
            return None
        v = 0
        for i, p in enumerate(self.uo_pins):
            v |= p.value() << i
        return v
