# Track B architecture and implementation notes

Internal notes on how the I3C target and the bridge work.
Check every frame against the MIPI I3C Basic v1.2 specification before freezing.

## Blocks and status

| Module | Owner | Status | Notes |
| --- | --- | --- | --- |
| `sync2_edge` | M4 | Done, unit-tested | I3C SCL/SDA and I2C SCL/SDA, no glitch filter |
| `i3c_bus_cond` | M3 | Done, unit-tested | START/Sr, STOP, HDR exit (4 SDA falls with SCL low) |
| `fifo4x8` | M4 | Done, unit-tested | Request, then response (inside `cmd_ctrl`) |
| `clkdiv` | M4 | Done, unit-tested | Quarter-period ticks for the I2C controller |
| `timeout20` | M4 | Done, unit-tested | One 20-bit inactivity timer inside `cmd_ctrl` (see Timeouts) |
| `cmd_ctrl` | M4 | Done, unit-tested | Header parser + FSM (CMD, ADDR, payload), status flags, timeouts |
| `i2c_ctrl` | M4 | Done, unit-tested | Downstream controller, clock stretching, abort |
| `i3c_tgt` | M3 | Done, top-level tests | Bit engine, protocol FSM, T-bit parity, SDA driver |
| `i3c_daa` | M3 | Done, top-level + two-bridge tests | DA register, 64-bit identity select |
| `project.v` | M3 | Done | Wiring and pin logic |

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

## Target FSM (i3c_tgt)

The state number is what DBG_STATE (`uo_out[3:0]`) shows.

| # | State | Enters on | Does |
| --- | --- | --- | --- |
| 0 | IDLE | reset, STOP, stall timeout | wait for START |
| 1 | ADDR | START or Sr | shift 7 address bits + R/W; match 7E, DA or static address |
| 2 | ACK | address (or ENTDAA DA) accepted | drive ACK open-drain until SCL falls |
| 3 | CCC | 7E/W ACKed | CCC code + T; parity error = TE1 |
| 4 | DAA_ID | 7E/R ACKed during ENTDAA | shift PID, BCR, DCR open-drain; lose if SDA reads 0 while sending 1 |
| 5 | DAA_ADDR | 64 bits sent, still winning | DA + parity; ACK and store if parity is good (else TE3 NACK) |
| 6 | SDASA | SETDASA, own static address ACKed | {DA, 0} + T; store DA (TE2 on bad parity) |
| 7 | PRIV_WR | DA/W ACKed | bytes + T into `cmd_ctrl` (TE2 on bad parity) |
| 8 | PRIV_RD | DA/R ACKed | bytes push-pull; T = 1 while more, T = 0 on the last byte |
| 9 | HDR | ENTHDR0-7 or TE0 | ignore everything until `hdr_exit` |
| 10 | WAIT | not addressed, NACK, error or lost arbitration | wait for Sr or P |

Details that follow from the spec subset:

- **Which addresses are ACKed.** 7E/W always. 7E/R only after ENTDAA and only
  without a dynamic address. The dynamic address only when no direct CCC is in
  progress, and only when `cmd_ctrl` can take the transfer (DA/W not during an
  I2C transaction, DA/R only with a response waiting). The static address only
  after SETDASA and only without a dynamic address.
- **CCC context.** ENTDAA, SETDASA and any other direct CCC set a context that
  lasts until STOP or the next 7E/W. Other direct CCCs (GETPID, GETBCR, ...) get
  the dynamic address NACKed; other broadcast CCCs are ignored after the parity check.
- **TE0.** The first header after a START that is 7E/W with exactly one bit
  wrong (3E, 5E, 6E, 76, 7A, 7C, 7F /W, or 7E/R) sends the target to HDR, where it
  waits for the HDR Exit Pattern.
- **End-of-Data.** The target drives T push-pull and lets go of SDA as SCL rises
  in the T-bit. With T = 1 the controller may pull SDA low while SCL is high:
  that is a repeated START, and the target stops sending.
- **Frames for `cmd_ctrl`.** `frame_start` when DA/W or DA/R is ACKed;
  `frame_end` at the STOP, Sr or stall timeout that ends it. A private write
  that ends mid-command is dropped.

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

## Timeouts

`src/timeout20.v` is the same 20-bit inactivity timer as Track A's own copy:
it counts while `run` is high, any `kick` restarts it, and `expired` pulses
after `limit` idle cycles (0 disables; 20 bits = 41.9 ms at 25 MHz). `cmd_ctrl`
uses one instance for both waits below; while an I2C transaction runs only I2C
progress restarts it, otherwise I3C SCL edges do. The limit is `TO_BUS` at the
top of `project.v`.

| Waiting for | Kicked by | Proposed limit | On expiry |
| --- | --- | --- | --- |
| Downstream I2C transaction (EXEC) | every byte popped or pushed | 875,000 (35 ms, SMBus tTIMEOUT; covers clock stretching) | Abort the I2C transfer (STOP), respond with status bit 4 set |
| I3C bus stalled mid-transfer (SCL stops between START and STOP, target not in IDLE or HDR) | every SCL edge | 875,000 (35 ms) | Release SDA, target FSM back to IDLE, end any open private frame (no status flag) |
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

## Area

175 flip-flops in the finished RTL against the plan's estimate of 171
(i3c_tgt 30, i3c_daa 8, cmd_ctrl 27, fifo4x8 39, timeout20 20, i2c_ctrl 29,
synchronisers 12, bus conditions 3, clkdiv 6, I2C_FAST latch 1). Check
utilisation in the first full hardening run.
