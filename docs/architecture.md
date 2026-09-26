# Track B architecture and implementation notes

Internal notes for building the I3C target on top of what exists today.
Check every frame against the MIPI I3C Basic v1.2 specification before freezing.

## Blocks and status

| Module | Owner | Status | Notes |
| --- | --- | --- | --- |
| `sync2_edge` | M4 | Done, unit-tested | I3C SCL/SDA and I2C SCL/SDA, no glitch filter |
| `i3c_bus_cond` | M3 | Done, unit-tested | START/Sr, STOP, HDR exit (4 SDA falls with SCL low) |
| `fifo4x8` | M4 | Done, unit-tested | Not wired yet |
| `clkdiv` | M4 | Done, unit-tested | Not wired yet; quarter-period ticks for the I2C controller |
| `timeout20` | M4 | Done, unit-tested | Not wired yet; 20-bit inactivity timer for `cmd_ctrl` (see Timeouts) |
| `project.v` | M3 | Skeleton | Drives nothing; DBG_STATE shows bus activity (scaffolding) |
| `cmd_ctrl` | M4 | Week 3 | Header parser + FSM (CMD, ADDR, payload), same format as the plan |
| `i3c_tgt` | M3 | Weeks 4-5 | Bit engine, protocol FSM, T-bit parity, SDA driver |
| `i2c_ctrl` | M4 | Weeks 4-5 | Downstream controller |
| `i3c_daa` | M3 | Week 6 | DA register, ENTDAA / SETDASA / RSTDAA, 64-bit ID shifter |

## Signal rules

- One clock, 25 MHz. Every pin goes through `sync2_edge`; logic uses the
  synchronised level and one-cycle `rise` / `fall` pulses. SCL and SDA see the
  same delay, so START/STOP ordering is preserved.
- The target changes its SDA drive only while SCL is low (after `scl` fall),
  except the End-of-Data hand-off: it lets go of SDA on SCL rise in a read T-bit.
- `uio_oe[2]` (I3C SCL) is always 0. `uio_out[7:6]` is always 0 (I2C open-drain).

## SDA driver (uio[3])

| Phase | uio_oe[3] | uio_out[3] |
| --- | --- | --- |
| Released | 0 | 0 |
| Open-drain 0 (ACK, ENTDAA ID bit 0) | 1 | 0 |
| Open-drain 1 (ENTDAA ID bit 1, NACK) | 0 | 0 |
| Push-pull data / T-bit | 1 | bit |

The testbench flags `i3c_sda_conflict` if the controller model and the bridge
ever drive opposite values, and `i3c_scl_driven` if the bridge drives SCL.

## Target FSM (for i3c_tgt)

| State | Enters on | Does |
| --- | --- | --- |
| IDLE | reset, STOP, error recovery | wait for START |
| ADDR | START or Sr | shift 7 address bits + R/W; match 7E, DA or static address |
| ADDR_ACK | 8 bits in | ACK (open-drain) if ours and ready, else NACK |
| CCC | 7E/W acked, then a byte | CCC code + T; parity error = TE1 |
| CCC_DATA | broadcast CCC with payload | receive and discard |
| DAA_ID | 7E/R acked during ENTDAA | shift PID, BCR, DCR open-drain; lose if SDA reads 0 while sending 1 |
| DAA_ADDR | 64 bits sent, still winning | DA + parity; ACK and store if parity is good (else TE3 NACK) |
| SDASA_DATA | SETDASA to own static address | {DA, 0} + T; store DA |
| PRIV_WR | DA/W acked | bytes + T into the command parser (TE2 on bad parity) |
| PRIV_RD | DA/R acked | bytes push-pull; T = 1 while more, T = 0 on the last byte |
| HDR | ENTHDRx or TE0 | ignore everything until `hdr_exit` |
| WAIT | error or lost arbitration | wait for Sr or P |

## Identity (proposed, confirm with the team)

| Field | Value |
| --- | --- |
| PID[47:33] MIPI manufacturer ID | 0x7FFF placeholder (no MIPI-assigned ID) |
| PID[32] ID type | 0 (fixed value) |
| PID[31:16] part ID | 0x0001 |
| PID[15:12] instance | {2'b00, ui_in[2:1]} |
| PID[11:0] vendor | 0x000 |
| BCR | 0x01 (target, max-data-speed limitation) |
| DCR | 0x00 (generic) |
| Static address | 7'h3A / 7'h3B (LSB = ui_in[0]) |

## Host protocol (private write / read)

CMD[7:6] op (00 write, 01 read, 10 write 1 byte then read, 11 status),
CMD[1:0] LEN-1; ADDR[6:0] downstream I2C address; then the payload.
The next private read returns the data, or one status byte for writes and
status: [7] I2C NACK, [6] I3C parity error, [5] FIFO overflow, [4] timeout,
[2:0] FIFO count. The target NACKs its read address while the I2C transfer is
still running.

## Timeouts (plan for cmd_ctrl, week 3)

`src/timeout20.v` is the same 20-bit inactivity timer as Track A's own copy:
it counts while `run` is high, any `kick` restarts it, and `expired` pulses
after `limit` idle cycles (0 disables; 20 bits = 41.9 ms at 25 MHz). Proposed
use, with the limits as constants at the top of `project.v`:

| Waiting for | Kicked by | Proposed limit | On expiry |
| --- | --- | --- | --- |
| Downstream I2C transaction (EXEC) | every byte popped or pushed | 875,000 (35 ms, SMBus tTIMEOUT; covers clock stretching) | Abort the I2C transfer (STOP), respond with status bit 4 set |
| I3C bus stalled mid-transfer (SCL stops between START and STOP) | every SCL edge | 875,000 (35 ms) | Release SDA, target FSM back to IDLE |
| Controller reading the response | - | none | The controller may poll as long as it likes |

## Test model: `test/models/i3c_controller.py`

| Method | Frame |
| --- | --- |
| `private_write(da, data, use_7e)` | S, [7E/W, Sr,] DA/W, bytes + T, P |
| `private_read(da, max_len, use_7e)` | S, [7E/W, Sr,] DA/R, bytes until T = 0 (aborts at max_len), P; `None` on NACK |
| `ccc_broadcast(code, payload)` | S, 7E/W, CCC + T, payload + T, P |
| `setdasa(sa, da)` / `rstdaa()` | direct SETDASA / broadcast RSTDAA |
| `entdaa(das)` | offers each address in turn, returns (PID, BCR, DCR, DA, acked) per target |
| `enthdr(mode)`, `hdr_traffic(n, rng)`, `hdr_exit(pulses)` | HDR entry, DDR-like noise, exit pattern |

Default SCL is 1 MHz (`period_ns=1000`). Read bits are sampled just before SCL
rises; data changes a quarter period after SCL falls.
