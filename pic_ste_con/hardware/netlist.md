# Netlist — 2-axis gripper demo carrier board

Rev A. Connections only; reasoning is in [pcb_spec.md](pcb_spec.md).

This board is a PCB version of a **working, tested perfboard build**. Where the
two differ, the difference is listed under "Additions" below with the reason.

Everything is **through-hole** — hand-soldered, single builder.

## Rails

| Net | From | To |
|---|---|---|
| `VM` | J1 (+), 24 V | U2 VM, U3 VS, U4 IN+, C1, C2, C4, C5, C6, TP1 |
| `GND` | J1 (−) | everything |
| `VSYS` | U4 OUT+ (3.3 V) | U1 pin 39, TP2 |
| `+3V3` | U1 pin 36 (3V3 OUT) | U2 VIO, U3 VDD, R2, R3, TP3 |

**`VSYS` and `+3V3` are two different nets and must never be joined.** The buck
feeds the Pico's *input* (VSYS); the Pico's internal regulator then feeds the
driver logic (3V3 OUT). Labelling both "3V3" shorts the buck output to the
Pico's regulator output.

**U1 pin 36 is 3V3 OUT. Pin 37 is 3V3_EN, an input** — the original Cirkit
drawing shows this wire on the pin-37 row.

## Parts

| Ref | Part | Symbol | Footprint |
|---|---|---|---|
| U1 | Raspberry Pi Pico 2W | `MCU_RaspberryPi:RaspberryPi_Pico_W` | `Module:RaspberryPi_Pico_Common_THT` |
| U2 | TMC2208 stepstick (SM1 platform) | `carrier-parts:TMC2208_StepStick` | `Module:Pololu_Breakout-16_15.2x20.3mm` |
| U3 | TMC2209 stepstick (SM2 gripper) | `carrier-parts:TMC2209_StepStick_BTT` | **custom, 17 pads** |
| U4 | MP1584 buck, 24 V → 3.3 V | **custom** | **custom**, 22 × 17 mm |
| J1 | DC barrel jack, 2.1 mm, 24 V | `Connector:Barrel_Jack` | `Connector_BarrelJack:BarrelJack_Horizontal` |
| J2 | SM1 motor | `Connector_Generic:Conn_01x04` | `Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical` |
| J3 | SM2 motor | `Connector_Generic:Conn_01x04` | `Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical` |
| J4 | HOME limit switch | `Connector_Generic:Conn_01x02` | `Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical` |
| J5 | Pause button | `Connector_Generic:Conn_01x02` | `Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical` |
| C1, C2 | 220 µF / 35 V electrolytic | `Device:C_Polarized` | `Capacitor_THT:CP_Radial_D10.0mm_P5.00mm` |
| C4–C8 | 100 nF / 50 V ceramic | `Device:C` | `Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm` |
| R1, R4, R5 | 1.0 kΩ | `Device:R` | `Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal` |
| R2, R3 | 10 kΩ | `Device:R` | same as above |
| TP1–TP4 | Test points | `Connector:TestPoint` | `TestPoint:TestPoint_Pad_2.0x2.0mm` |

## Nets

### SM2 gripper (TMC2209) — validated on the perfboard build

```
SM2_STEP    U1.4    U3.7  (STEP)
SM2_DIR     U1.5    U3.8  (DIR)
SM2_EN      U1.6    U3.1  (EN)     R3.1
SM2_DIAG    U1.7    U3.17 (DIAG)
SM2_UART_TX U1.1    R1.1
SM2_UART    R1.2    U1.2   U3.4 (RX)
```

R1 (1 kΩ) sits in the TX leg only; RX taps the shared node directly. This is
half-duplex single-wire UART, unchanged from the working build.

### SM1 platform (TMC2208)

```
SM1_EN      U1.24   U2.1  (EN)     R2.1
SM1_STEP    U1.25   U2.7  (STEP)
SM1_DIR     U1.26   U2.8  (DIR)
```

### Switch inputs

```
HOME_SW_PIN U1.27   R4.1   C7.1
HOME_SW     R4.2    J4.1
PAUSE_PIN   U1.29   R5.1   C8.1
PAUSE_BTN   R5.2    J5.1
```

C7.2, C8.2, J4.2, J5.2 → `GND`. No external pull-ups — the firmware uses
`Pin.PULL_UP`, and both `*_ACTIVE_LOW` flags are `True`.

### Motors — keep each coil pair on adjacent pins

```
SM1_M1A  U2.13  J2.1     SM2_A1  U3.13  J3.1
SM1_M1B  U2.14  J2.2     SM2_A2  U3.14  J3.2
SM1_M2A  U2.12  J2.3     SM2_B1  U3.12  J3.3
SM1_M2B  U2.11  J2.4     SM2_B2  U3.11  J3.4
```

### Power pins

```
VM    J1.1   U2.16  U3.16  U4.IN+  C1.+  C2.+  C4.1  C5.1  C6.1  TP1
GND   J1.2   J1.3   U2.9   U2.15   U3.9  U3.15  U4.IN-  U4.OUT-
      C1.-  C2.-  C4.2  C5.2  C6.2  C7.2  C8.2  J4.2  J5.2
      U1.3  U1.8  U1.13  U1.18  U1.23  U1.28  U1.33  U1.38   TP4
VSYS  U4.OUT+  U1.39  TP2
+3V3  U1.36  U2.10  U3.10  R2.2  R3.2  TP3
```

### Deliberately unconnected

- U2: MS1(2), MS2(3), PDN(4), USART(5), CLK(6)
- U3: MS1(2), MS2(3), TX(5), CLK(6), INDEX(18)

**MS1/MS2 are left floating on purpose**, exactly as on the working perfboard.
That gives 1/8 microstepping on both drivers, which is what `SM2_MICROSTEPS = 8`
assumes and what `SM1_MAIN_ABS = -10000` was measured at. Adding jumpers could
only change a proven setting.

## Additions not present in the tested build

Only three, each with the failure it prevents:

| Part | Why |
|---|---|
| R2, R3 (10 kΩ, EN → 3V3) | The Pico's pins float for ~200 ms at power-on before firmware runs. EN is active-low, so a floating pin lets both motors energise before any code is in control. These hold both axes off until firmware deliberately switches them on. |
| R4/C7, R5/C8 (1 kΩ + 100 nF) | Motor cables radiate interference; the long switch wire picks it up as a spike that looks identical to a switch press. The filter needs 0.1 ms of steady voltage to respond — a spike lasts microseconds and is ignored, a real press lasts tens of milliseconds and passes. **Fixes the false limit-switch triggers already seen on the rig.** |
| TP1–TP4 | Bare pads to probe with a multimeter during bring-up, so 24 V and 3.3 V can be verified *before* modules are fitted. |

Deliberately **not** included, by decision: fuse, reverse-polarity diode, TVS,
screw terminal, MS jumper straps.

## Stepstick pinouts — confirmed against the physical modules

Symbols are in `carrier-parts.kicad_sym` in the KiCAD project folder, generated
from the module silkscreens. Numbering follows KiCad's stock
`Pololu_Breakout-16`: pads **1–8 down the left column, 9–16 up the right**, so
pad 16 is top-right.

`TMC2209_StepStick_BTT` — 18 pins:

| Pad | Name | | Pad | Name |
|---|---|---|---|---|
| 1 | EN | | 16 | VS |
| 2 | MS1 | | 15 | GND |
| 3 | MS2 | | 14 | A2 |
| 4 | **RX** | | 13 | A1 |
| 5 | TX | | 12 | B1 |
| 6 | CLK | | 11 | B2 |
| 7 | STEP | | 10 | VDD (VIO) |
| 8 | DIR | | 9 | GND |
| 17 | DIAG | | 18 | INDEX |

DIAG and INDEX are pads on the module's **top edge**, outside the 16-pin array —
which is why this needs a custom 17-pad footprint. DIAG sits **5.08 mm** from EN
(measured 5.05 mm; 5.08 is the exact 2 × 0.1" grid value).

`TMC2208_StepStick` — 16 pins:

| Pad | Name | | Pad | Name |
|---|---|---|---|---|
| 1 | EN | | 16 | VM |
| 2 | MS1 | | 15 | GND |
| 3 | MS2 | | 14 | M1B |
| 4 | PDN | | 13 | M1A |
| 5 | USART | | 12 | M2A |
| 6 | CLK | | 11 | M2B |
| 7 | STEP | | 10 | VIO |
| 8 | DIR | | 9 | GND |

Coil pair naming differs between the two: `A1+A2` / `B1+B2` on the 2209,
`M1A+M1B` / `M2A+M2B` on the 2208.

### Do not reuse third-party stepstick symbols

A SnapEDA `SilentStepStick` symbol was evaluated and rejected. Its pin *names*
do not match a BIGTREETECH board: by position its `SPRD` pin lands on the BTT
board's `RX` pad, and `PDN`/`UART` land on `CLK`/`TX`. Wiring UART by name
against it connects nothing, while the schematic still looks correct.

## Board targets

| Property | Value |
|---|---|
| Stackup | 2-layer, 1.6 mm FR4, 1 oz |
| Outline | 100 × 80 mm |
| Mounting | 4× M3 (3.2 mm), 5 mm in from each corner |
| Fab | JLCPCB (minimum order 5 boards) |
| POWER/MOTOR net class | 1.5 mm track, 0.4 mm clearance (sized for 2 A) |
| RAIL net class (`VSYS`, `+3V3`) | 0.8 mm track |
| Default net class | 0.3 mm track, 0.25 mm clearance |
| Ground | Full B.Cu pour, stitched on ~10 mm grid |

## Open

- **MP1584 pad positions.** Body is 22 × 17 mm; the four hole positions are still
  unmeasured. Needed before the footprint can be drawn (Stage 3), not before the
  schematic.
