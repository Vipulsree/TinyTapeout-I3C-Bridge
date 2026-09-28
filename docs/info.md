<!---
This file is used to generate the project datasheet.
-->

## How it works

The bridge is a minimal MIPI I3C Basic SDR target. An I3C controller gives it a
dynamic address with ENTDAA, then uses
private writes and reads to run I2C transactions on a downstream I2C bus.
It is half-duplex: it stores the request, runs it, then returns the response.

A private write carries a 2-byte header and a payload:

- **CMD:** bits 7:6 = op (00 write, 01 read, 10 write 1 byte then read, 11 status); bits 1:0 = length - 1 (1-4 bytes).
- **ADDR:** 7-bit address of the downstream I2C device.

The next private read returns the data (the target ends it with T = 0), or one
status byte for writes: bit 7 I2C NACK, bit 6 I3C parity error, bit 5 FIFO
overflow, bit 4 timeout, bits 2:0 FIFO count. A downstream I2C transfer that
stalls for 35 ms (for example a sensor holding SCL low) is aborted by a 20-bit
timeout and reported with bit 4. While the I2C transfer runs, the bridge NACKs its
read address and the controller retries; `IRQ` shows when the response is ready.

Supported: 7'h7E broadcast, private write/read, ENTDAA, RSTDAA,
odd-parity T-bits, End-of-Data, HDR entry detection and HDR exit.
Not supported: in-band interrupts, Hot-Join, HDR data, other CCCs (broadcast
ones are ignored, direct ones NACKed).
The I3C bus must run at 1 MHz or slower (BCR bit 0 advertises the limit).

`uo_out[3:0]` shows the target state: 0 idle, 1 address, 2 ACK, 3 CCC,
4 ENTDAA identity, 5 ENTDAA address, 6 private write, 7 private read,
8 HDR (ignoring the bus), 9 waiting for Sr or STOP.

## How to test

1. Clock 25 MHz. Connect the RP2040 I3C controller firmware to `uio[2]` (SCL)
   and `uio[3]` (SDA) with a 2.2 kOhm pull-up on SDA.
2. Run ENTDAA; `DA_VALID` (`uo_out[4]`) goes high.
3. Plug an I2C temperature-sensor Pmod into the bottom `uio` row, send a private
   write `81 48 00`, then a private read to get 2 bytes of temperature.

## External hardware

- RP2040 on the demo board running the I3C controller firmware
- 2.2 kOhm pull-up on I3C SDA
- I2C temperature-sensor Pmod (Tiny Tapeout bottom-row I2C pinout), with pull-ups
