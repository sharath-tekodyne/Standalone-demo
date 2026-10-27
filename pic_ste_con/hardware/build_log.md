# KiCAD build log — GRIPPER-CARRIER rev A

One row per stage as you finish it. Record what went wrong, not just that it
passed — the corrections are what rev B starts from.

Tool: KiCAD 10.0.5. Stage sequence: see the approved plan.
Connections: [netlist.md](netlist.md). Rationale: [pcb_spec.md](pcb_spec.md).

**Project path:** `C:\Users\sudha\OneDrive\Desktop\Standalone-carrier-board`

## Progress

| Stage | What | Date | Status | Notes / what went wrong |
|---|---|---|---|---|
| 0.1 | Create project | | not started | |
| 0.2 | Custom stepstick symbols | | not started | |
| 0.3 | Custom MP1584 symbol + footprint | | not started | |
| 1.1 | Power input stage | | not started | |
| 1.2 | Buck converter | | not started | |
| 1.3 | Pico + 3V3 rail | | not started | |
| 1.4 | TMC2209 power + MS straps | | not started | |
| 1.5 | TMC2209 logic + UART | | not started | |
| 1.6 | TMC2208 complete block | | not started | |
| 1.7 | Motor connectors J2/J3 | | not started | |
| 1.8 | Sensor connectors J4/J5 + RC | | not started | |
| 2 | **GATE:** ERC + net diff | | not started | |
| 3 | Footprint assign + PCB import | | not started | |
| 4 | Board setup: stackup, rules, net classes | | not started | |
| 5 | Outline + placement | | not started | |
| 6 | Route power + motor by hand | | not started | |
| 7 | Route signal nets | | not started | |
| 8 | Ground pour + stitching | | not started | |
| 9 | **GATE:** DRC + parity | | not started | |
| 10 | Silkscreen + fab output | | not started | |

## Decisions made during the build

Record anything that departs from the plan, and why.

| Date | Decision | Reason |
|---|---|---|
| 2026-08-04 | Buck is MP1584 only — single footprint, no dual-pad pattern | User decision. Risk understood: 28 V rating on a 24 V rail, no TVS can cover the 24–28 V window, and a hot-plug LC transient can ring past it. Mitigation is procedural: never hot-plug, switch at the supply with the jack already connected. Keep a spare module. |
| 2026-08-04 | Project lives in OneDrive | User decision. Watch for sync conflicts on `.kicad_pcb` during long routing sessions; back up before one. |

## Deferred to rev B

Things noticed but deliberately not fixed in rev A.

| Item | Why deferred |
|---|---|
| | |

## Provenance

- **The SM2 (TMC2209) circuit is validated hardware**, not a proposal. The Cirkit
  drawing records a build soldered on perfboard that actually runs the gripper:
  UART via 1 kΩ, GP2/3/4/5 → STEP/DIR/EN/DIAG, VIO from Pico 3V3, VM + 220 µF.
  Treat that connectivity as confirmed.
- **What perfboard cannot validate is footprint geometry.** On perfboard any pin
  is reachable by wire; on the PCB the module connects only through the 16 pads
  of `Pololu_Breakout-16`. Open question: is DIAG one of those 16, or a separate
  pad by the trimpot? If separate, the footprint needs a 17th pad.
- **SM1 (TMC2208), the limit switch and the button are NOT in that drawing.**
  Pin assignments come from `protocol.py` and are correct, but the TMC2208
  module's pin order is unverified.

## Known carry-overs from the reference circuit

Already corrected in this design — listed so they are not reintroduced.

- 3V3 taken from Pico **pin 36** (3V3 OUT), not pin 37 (3V3_EN, an input). The
  original Cirkit drawing shows the wire on the pin-37 row.
- Bulk caps re-rated to 35 V for the 24 V supply.
- EN pull-ups (R2, R3) added — without them both drivers are energized from
  power-on until firmware runs `motor.disable()`.
- Fuse, reverse-polarity Schottky and TVS added; the reference had no protection.
- Buck specified ≥ 40 V input. An MP1584 tops out near 28 V, too close to 24 V.
- Sensor connectors are 2-pin, signal + GND. Firmware supplies the pull-up.
- Stepstick pin rows are **12.7 mm** apart, not 15.24 mm. The KiCAD footprint
  `Pololu_Breakout-16_15.2x20.3mm` is named after the module *body* size.
- Stepstick symbols are based on `Conn_02x08_Counter_Clockwise`, not
  `Conn_02x08_Odd_Even` — the footprint numbers its pads counter-clockwise, and
  the Odd_Even variant would silently swap nearly every pin.
