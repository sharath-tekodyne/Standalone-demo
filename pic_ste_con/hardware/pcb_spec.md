# Carrier PCB — 2-axis gripper demo

A socketed carrier board for the firmware in this repo. Every GPIO assignment
below is taken from `protocol.py`; that file stays the source of truth, and any
pin change there is a board change here.

Scope: SM1 (platform, TMC2208) + SM2 (gripper, TMC2209) + HOME limit switch +
pause button, on one board. All four modules (Pico, both stepsticks, buck) are
socketed, not soldered down.

Supply: 24 V at the input jack.

## Modules and connectors

| Ref | Part | Mounting |
|---|---|---|
| U1 | Raspberry Pi Pico 2 / 2W | 2× 20-way female header, 0.1", 17.78 mm rows |
| U2 | TMC2208 stepstick (SM1, platform) | 2× 8-way female header, 0.1", **12.7 mm** rows |
| U3 | TMC2209 stepstick (SM2, gripper) | 2× 8-way female header, 0.1", **12.7 mm** rows |
| U4 | Buck module, 24 V in → 5 V out | 4-pad module footprint |
| J1 | DC power in, 24 V | barrel jack + parallel 2-pin screw terminal |
| J2 | SM1 motor | 4-pin JST-XH |
| J3 | SM2 motor | 4-pin JST-XH |
| J4 | HOME limit switch | 2-pin JST-XH (GP21 / GND) |
| J5 | Pause button | 2-pin JST-XH (GP22 / GND) |

J4/J5 are signal + GND only. Both switches are plain dry contacts to ground and
the firmware supplies the pull-up internally, so there is nothing to power at the
far end.

## Net list

### Pico → TMC2209 (SM2, gripper) — as drawn in the reference circuit

| Pico | Net | U3 pin | protocol.py |
|---|---|---|---|
| GP0 (pin 1) | SM2_UART_TX | → R1 (1.0 kΩ) → PDN_UART | `SM2_UART_TX_PIN = 0` |
| GP1 (pin 2) | SM2_UART | PDN_UART (direct) | `SM2_UART_RX_PIN = 1` |
| GP2 (pin 4) | SM2_STEP | STEP | `SM2_STEP_PIN = 2` |
| GP3 (pin 5) | SM2_DIR | DIR | `SM2_DIR_PIN = 3` |
| GP4 (pin 6) | SM2_EN | EN | `SM2_EN_PIN = 4` |
| GP5 (pin 7) | SM2_DIAG | DIAG | `SM2_DIAG_PIN = 5` |

TX and RX meet at the single PDN_UART pad with R1 only in the TX leg — standard
half-duplex single-wire UART, unchanged from the reference circuit.

### Pico → TMC2208 (SM1, platform)

| Pico | Net | U2 pin | protocol.py |
|---|---|---|---|
| GP18 (pin 24) | SM1_EN | EN | `SM1_EN_PIN = 18` |
| GP19 (pin 25) | SM1_STEP | STEP | `SM1_STEP_PIN = 19` |
| GP20 (pin 26) | SM1_DIR | DIR | `SM1_DIR_PIN = 20` |

No UART on SM1 — the driver runs in standalone STEP/DIR mode, which is what
`tmc2208.py` assumes.

### Pico → switches

| Pico | Net | Goes to | protocol.py |
|---|---|---|---|
| GP21 (pin 27) | HOME_SW | J4 pin 1, via R4 (1 kΩ) | `SM1_HOME_SWITCH_PIN = 21` |
| GP22 (pin 29) | PAUSE_BTN | J5 pin 1, via R5 (1 kΩ) | `PAUSE_BUTTON_PIN = 22` |

Both are wired switch-to-GND and rely on the RP2040/RP2350 internal pull-up
(`Pin.PULL_UP` in `main.py`), matching `HOME_SWITCH_ACTIVE_LOW = True` and
`PAUSE_BUTTON_ACTIVE_LOW = True`. R4/R5 with C7/C8 (100 nF to GND at the Pico
pin) form an RC filter — a mechanical switch on a long lead running beside two
stepper harnesses will otherwise pick up enough noise to false-trigger. The
firmware's 30 ms debounce handles contact bounce; this handles electrical noise,
which the debounce can't.

### Power

| Net | Sources | Loads |
|---|---|---|
| VIN | J1 + | F1 → D1 → VM |
| VM (24 V) | D1 cathode | U2 VM, U3 VM, U4 IN+, C1, C2, C3 |
| +5V | U4 OUT+ | U1 VSYS (pin 39) |
| +3V3 | U1 3V3 OUT (pin 36) | U2 VIO, U3 VIO, R2, R3, JP1–JP4 pin 3 |
| GND | J1 −, everything | star at the input, single pour |

**U1 3V3 is pin 36 (3V3 OUT), not pin 37 (3V3_EN).** The reference drawing shows
this wire landing on the pin-37 row; 3V3_EN is an input and cannot source VIO, so
the board uses pin 36.

## Added parts (not in the reference circuit)

| Ref | Value | Why |
|---|---|---|
| F1 | 2 A slow-blow, in a clip | A shorted coil or a reversed motor connector otherwise dumps the full supply into the board. |
| D1 | Schottky, ≥ 40 V, ≥ 3 A (SS36 / SMC) | Series reverse-polarity block. Costs ~0.5 W at full load; simpler and more reliable than a P-FET ideal-diode for this current. |
| TVS1 | SMAJ26A (26 V standoff, uni) | Clamps the inductive kick when a motor is unplugged live, and the surge from a plugged-in supply. |
| C1, C2 | 220 µF, **35 V**, one per stepstick | Bulk, sited within ~10 mm of each driver's VM pin. **The reference 220 µF is likely a 16 V part — it must be re-rated for 24 V.** |
| C3 | 100 µF, 35 V | Input bulk, after D1. |
| C4–C6 | 100 nF, 50 V X7R | HF decoupling at each stepstick VM and at the buck input. |
| R2, R3 | 10 kΩ, EN → 3V3 | **Safety.** Pico GPIOs are high-impedance inputs at reset and during the ~200 ms before `main.py` calls `motor.disable()`. EN is active-low; floating low means both drivers are energized before any firmware runs. These hold both axes disabled until firmware deliberately drives EN low. |
| R4, R5 | 1 kΩ series | Switch input RC, see above. |
| C7, C8 | 100 nF | Switch input RC, see above. |
| TP1–TP4 | Test points | VM, +5V, +3V3, GND. |

## Straps and adjustments that must stay accessible

1. **MS1/MS2 on both stepsticks — 3-pin jumpers (GND / pin / VIO), not floating.**
   On U3 this matters more than it looks. `main.py` calls
   `motor2.set_microsteps(8)` (writes MRES into CHOPCONF) and then
   `motor2.configure_stallguard()` writes `GCONF = 0`, which clears
   `mstep_reg_select` — so the chip reverts to taking microstepping from the MS
   pins and the register write is discarded. The rig currently lands on 1/8
   anyway because the MS pins sit low, i.e. it works by coincidence. Explicit
   straps make it deliberate. Verify the MS truth table against the TMC2209
   datasheet before committing the default.
2. **Vref trimpot on both stepsticks must remain reachable with the modules
   seated.** `IRUN` (set over UART on U3) scales against Vref, so grip force
   depends on that pot — it is a live calibration knob, not a set-and-forget.
   Do not place tall parts or the motor connectors where they block it.
3. **SM1 microstepping changes every SM1 step constant.** `SM1_MAIN_ABS =
   -10000` and `SM1_REACH_ABS = -7000` were measured at the module's current MS
   setting. Set the U2 straps to match whatever that module is jumpered to today,
   or re-measure both.

## Layout notes

- 2 layers, 1.6 mm, top signal + bottom GND pour, ~100 × 80 mm.
- Motor and VM traces: 1.5 mm minimum (2 A with margin). Logic: 0.25 mm.
- Keep the SM2 UART trace and the DIAG trace short and away from the motor
  outputs. StallGuard sensitivity is the whole point of that axis, and a
  DIAG line coupled to a coil is a false grip.
- Bulk caps within 10 mm of their driver's VM/GND pins, on the same layer.
- 4× M3 mounting holes, 5 mm from each corner.
- Both stepsticks need heatsink clearance above and airflow; do not tuck them
  under the Pico.

## Open items

- Buck module input rating: an MP1584 mini tops out at ~28 V, which is thin
  margin at 24 V nominal. Prefer a module rated ≥ 40 V in, trimmed to 5.0 V.
- Motor coil pairing (which of A1/A2/B1/B2 goes to which motor lead) depends on
  the specific motors; J2/J3 are just 4-pin passthroughs to the driver, so this
  is a harness question, not a board question.
- `SM1_INVERT_DIR` and `SM2_INVERT_DIR` are both `True` in `protocol.py` because
  coils were soldered reversed on the current build. A fresh harness may not need
  that — check direction on first power-up and flip those flags rather than
  rewiring.
