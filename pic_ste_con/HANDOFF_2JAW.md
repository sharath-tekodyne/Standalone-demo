# Handoff: the 2-jaw gripper demo

Companion to `HANDOFF_SM1_AND_4JAW.md`. Same rig, same GPIOs, same drivers —
different choreography and a different architecture.

Self-contained: every constant below is a real, tested value.

---

# 1. What the 2-jaw demo is

A simple pick-and-place shuttle. The carriage runs out to a pick point, the jaws
close on an object, it carries the object back to HOME, releases it, and repeats.

Compared to the 4-jaw demo there is **no REACH position and no inside pick**.
The jaws only ever grip from the outside. It is the simpler of the two demos and
the right one to bring up first.

## Architecture — this one runs on the Pico, not the PC

The 4-jaw demo is played by the host: the PC sends one command, waits for the
reply, sends the next. The 2-jaw demo is the opposite. **The sequence lives in
firmware.** After every phase the Pico writes its current phase and positions to
a file on flash, so it runs from a button press with no computer attached, and a
power cut mid-cycle resumes the same phase on reboot.

If you only need a bench demo with a laptop attached, §7 gives the same sequence
as a flat command list you can play from the host instead — much less code.

---

# 2. The sequence

Two priming phases run **once**, then a four-phase body repeats forever.

```
RELEASE           open the jaws fully, dropping anything held      (once)
   ↓
HOMING            drive SM1 into the limit switch, zero position   (once)
   ↓
OUT_TO_MAIN  ←────────────┐   move SM1 to MAIN, jaws open
   ↓                      │
CLOSE_GRAB                │   close the jaws onto the object
   ↓                      │
BACK_TO_HOME              │   carry it to HOME (step 0)
   ↓                      │
OPEN_RELEASE  ────────────┘   open fully, release      → cycle_count += 1
```

As a phase-transition table:

| Phase | Action | Next |
|---|---|---|
| `RELEASE` | `gripper.open_to_stop()` | `HOMING` |
| `HOMING` | `platform.home()` | `OUT_TO_MAIN` |
| `OUT_TO_MAIN` | `platform.move_to_absolute(-10000)` | `CLOSE_GRAB` |
| `CLOSE_GRAB` | `gripper.close_and_verify_grip()` | `BACK_TO_HOME` |
| `BACK_TO_HOME` | `platform.move_to_absolute(0)` | `OUT_TO_MAIN_2`→ see note |
| `OPEN_RELEASE` | `gripper.open_gripper()` | `OUT_TO_MAIN` |

Note: in the 2-jaw mode `BACK_TO_HOME` goes straight to `OPEN_RELEASE`. The
`OUT_TO_MAIN_2` phase exists only in the 4-jaw mode, which carries the object
back out before releasing it.

```python
NEXT_PHASE_TWO_JAW = {
    PHASE_RELEASE:      PHASE_HOMING,
    PHASE_HOMING:       PHASE_OUT_TO_MAIN,
    PHASE_OUT_TO_MAIN:  PHASE_CLOSE_GRAB,
    PHASE_CLOSE_GRAB:   PHASE_BACK_TO_HOME,
    PHASE_BACK_TO_HOME: PHASE_OPEN_RELEASE,
    PHASE_OPEN_RELEASE: PHASE_OUT_TO_MAIN,   # loop point, skips priming
}
CYCLE_END_PHASE = PHASE_OPEN_RELEASE          # one carry-and-release = one cycle
```

The loop point is what makes priming happen only once — `OPEN_RELEASE` jumps
back to `OUT_TO_MAIN`, never to `RELEASE`.

## Why RELEASE comes before HOMING

This ordering is not cosmetic. If the rig lost power with the jaws clamped on an
object, that object is still held at boot. Homing drives the carriage along the
rail, and a clamped object can foul the mechanism and stop SM1 ever reaching the
limit switch. So the jaws are opened **first**, dropping whatever they hold, and
only then does the carriage move.

When nothing is held, opening an already-open gripper does nothing, so this
costs a second and is otherwise invisible.

---

# 3. All the limits

## SM1 — platform axis

| Constant | Value | Meaning |
|---|---|---|
| `HOME` | `0` | Found physically by the limit switch, never stored |
| `SM1_MAIN_ABS` | `-10000` | Pick point, absolute steps from HOME. Negative = away from switch |
| `SM1_DEMO_SPEED_US` | `450` | Step half-period during the demo — smaller is faster |
| `DEFAULT_CHUNK_STEPS` | `100` | Motion is chunked this small so pause responds quickly |
| `HOMING_SPEED_US` | `900` | Fast approach |
| `HOMING_SLOW_US` | `1600` | Slow re-approach, for a repeatable zero |
| `HOMING_START_US` | `2000` | Ramp starts here, accelerating to the target |
| `HOMING_RAMP_STEPS` | `300` | Ramp length |
| `HOMING_BACKOFF_STEPS` | `400` | Back off this far between approaches |
| `HOMING_MAX_STEPS` | `200000` | Give up with an error rather than grind forever |
| Microstepping | 1/8 | MS1/MS2 left unconnected |

`SM1_MAIN_ABS = -10000` is the original rig's mechanics. Different hardware needs
a different number — jog out and read the position, don't copy it blindly.

## SM2 — gripper axis

| Constant | Value | Meaning |
|---|---|---|
| `OPEN` | `0` | Re-zeroed at the physical open stop on every boot |
| `sm2_closed_steps` | **calibrated** | Fully-shut jaw position. No default — must be marked per rig and is saved to flash |
| `SM2_GRIP_SPEED_US` | `600` | Step half-period for closing and open-to-stop |
| `SM2_MICROSTEPS` | `8` | Set over UART at boot |
| `SM2_OPEN_GRIP_MAX` | `800` | Cap on the open search when CLOSED isn't known |
| `SM2_OPEN_STOP_MARGIN` | `300` | Extra travel past known open, to seat on the hard stop |
| `SM2_GRIP_OVERTRAVEL` | `300` | Force mode only: steps commanded past fully-shut |
| `SM2_GRIP_MARGIN` | `60` | Force mode only: stalling this far short of shut = a real grip |
| `DEFAULT_STALLGUARD_THRESHOLD` | `75` | 0–255; DIAG trips when load drops below threshold×2 |
| `SM2_DEMO_TORQUE` | `MEDIUM` | IRUN 16 |
| `GRIPPER_FORCE_FEEDBACK` | `False` | See below — this matters a lot |

**Only one thing needs calibrating by hand: `sm2_closed_steps`.** HOME is a
switch, MAIN is a constant, OPEN is re-found every boot. Jog the jaws fully shut
with nothing between them, send `SM2 MARK CLOSED`, and it persists.

---

# 4. How the gripper actually closes

This is the part most likely to surprise you, so read it before implementing
`CLOSE_GRAB`.

**StallGuard does not work reliably on the closing stroke on this rig.** The
intended design was force feedback: close until the motor feels resistance, and
that resistance is the object. In practice the load signal on the close stroke
was not distinguishable enough to trip reliably, so the demo runs with
`GRIPPER_FORCE_FEEDBACK = False` and closes **by position** instead.

## Position mode (what actually runs)

```python
def _close_to_position(self):
    remaining = self.state["sm2_closed_steps"] - self.state["sm2_position_steps"]
    if remaining != 0:
        direction = self.motor.CW if remaining > 0 else self.motor.ACW
        _, completed = self.motor.move_steps(
            direction, abs(remaining), speed_us=self._speed_us(), watch_stall=False)
        self.state["sm2_position_steps"] += completed if direction == self.motor.CW else -completed
    self.state["gripper_state"] = GRIPPER_CLOSED
    self.persist()
    return False
```

The jaws drive open-loop to the calibrated CLOSED position and hold there with
motor current. There is no detection — you set CLOSED to the jaw position that
clamps your object, and every close returns to exactly that position.

**Why this is repeatable despite being open-loop:** every boot, `RELEASE` drives
the jaws to the physical open stop and re-zeros the count there. Any drift
accumulated during the run is wiped at that hard stop, so CLOSED always means
the same physical opening.

## Force-feedback mode (if your rig's StallGuard behaves)

If you get a usable signal, set `GRIPPER_FORCE_FEEDBACK = True` and closing
becomes:

Drive **past** fully-shut by `SM2_GRIP_OVERTRAVEL` (300 steps), so the motor is
forced to jam either on the object (early) or on the jaws' own hard stop (at
full travel). StallGuard trips in both cases. Then classify by **where** it
stopped:

```python
gap = full - position          # >0 means it stopped short of fully shut
gripped = stalled and gap >= SM2_GRIP_MARGIN     # 60 steps
```

Stopping 60+ steps short means something was in the way — a real grip. Stopping
at roughly full travel means the jaws just closed on nothing. Both are normal
outcomes; only "nothing there" when you expected an object is a problem, and
that's a rig issue, not a software one.

## Opening — two different operations

These are not interchangeable, and using the wrong one is a classic bug.

**`open_to_stop()` — used by `RELEASE` only, at boot.** Ignores the tracked
position entirely and drives toward the physical open stop watching StallGuard,
capped at `abs(closed) + 300` steps. Then declares that stop to be step 0.

Needed because `open_gripper()` is a *relative* move to step 0 — if the count
already reads 0 while the jaws are physically clamped shut (which is exactly what
a mid-grip power cut leaves behind), it moves nothing and looks like "the gripper
won't open".

**`open_gripper()` — used by `OPEN_RELEASE`, mid-cycle.** A plain move back to
step 0 with StallGuard **off**. The count is trustworthy here because the close
that preceded it was tracked. StallGuard is off deliberately: a DIAG blip while
opening was aborting the move and producing false "stalled while opening" errors.

---

# 5. Persistence and resumability

Every phase transition and every completed motion chunk is written to flash
before `tick()` returns.

```python
def save(self):
    with open(self.tmp_path, "w") as handle:
        json.dump(self.data, handle)
    try:
        os.remove(self.path)     # some MicroPython VFS drivers won't
    except OSError:              # overwrite on rename
        pass
    os.rename(self.tmp_path, self.path)
```

Write to a temp file then rename, so a power cut mid-write cannot leave a
half-written unreadable state file.

What gets stored: `demo_phase`, `demo_running`, `cycle_count`,
`sm1_position_steps`, `sm2_position_steps`, `sm2_closed_steps`, the speed and
torque settings, and `needs_attention`.

## Boot safety — do not skip this

```python
state = store.load(DEFAULT_STATE)

if state.get("demo_running"):
    state["demo_running"] = False        # never resume motion by itself
if state.get("sm1_enabled") or state.get("sm2_enabled"):
    state["sm1_enabled"] = False         # both drivers come up de-energised
    state["sm2_enabled"] = False
```

`main.py` auto-runs on every power-up. Without this, a rig that lost power
mid-cycle would start moving the instant power returned, with nobody expecting
it. An operator must press the button or send `DEMO RESUME`.

Also drop any phase name this firmware doesn't recognise, so an old state file
from a previous build starts cleanly instead of resuming into an undefined phase:

```python
valid = (PHASE_HOMING,) + tuple(NEXT_PHASE.keys())
if state.get("demo_phase") not in valid:
    state["demo_phase"] = None
```

## The tick loop

```python
def tick(self, poll_inputs):
    if not self.state.get("demo_running"):   return
    if self.state.get("needs_attention"):    return
    phase = self.state.get("demo_phase")
    if phase is None:                        return

    def should_pause():
        poll_inputs()                        # service serial + button mid-move
        return not self.state.get("demo_running", False)

    if phase == PHASE_RELEASE:
        if self.gripper.open_to_stop(should_pause):        self._advance(phase)
    elif phase == PHASE_HOMING:
        if self.platform.home(self.switch_read, should_pause): self._advance(phase)
    elif phase == PHASE_OUT_TO_MAIN:
        if self.platform.move_to_absolute(SM1_MAIN_ABS, should_pause): self._advance(phase)
    elif phase == PHASE_BACK_TO_HOME:
        if self.platform.move_to_absolute(0, should_pause): self._advance(phase)
    elif phase == PHASE_OPEN_RELEASE:
        if self.gripper.open_gripper(should_pause):        self._advance(phase)
    elif phase == PHASE_CLOSE_GRAB:
        # True (gripped) and False (nothing there) both advance.
        # Only None means "paused mid-close, retry this phase".
        if self.gripper.close_and_verify_grip(should_pause) is not None:
            self._advance(phase)
```

**Every phase handler returns a boolean that gates the advance.** Returning
False means "interrupted, stay in this phase" — so a resume retries the same
phase from the current position. That single convention is the whole
resumability mechanism; there is no separate recovery code.

Homing is idempotent, so retrying it from anywhere is always safe.

---

# 6. Faults and the pause button

Wrap the tick in a handler that stops and de-energises rather than continuing
blindly:

```python
while True:
    try:
        demo.tick(poll_inputs)
    except Exception as exc:
        demo.pause()
        set_sm1_enabled(False)          # de-energise both on an unexpected fault
        set_sm2_enabled(False)
        state["needs_attention"] = True
        persist()
        print("ERR DEMO {}: {}".format(type(exc).__name__, exc))
    poll_inputs()
    if not state.get("demo_running", False):
        time.sleep_ms(10)
```

`needs_attention` blocks `tick()` from doing anything until an operator clears it
by resuming, so a rig with a real problem stops instead of grinding.

## The button

One physical button on GP22, wired to ground with the internal pull-up, doing
three jobs based on state:

```python
def _on_button_press():
    if state.get("demo_running"):        demo.pause();  return
    if state.get("demo_phase") is not None:
        demo.resume(); set_sm1_enabled(True); set_sm2_enabled(True); return
    demo.start();  set_sm1_enabled(True); set_sm2_enabled(True)
```

First press starts, then it toggles pause and resume. Debounce by requiring a
reading to be stable for `BUTTON_DEBOUNCE_MS = 30`, and act only on the press
edge, not the release.

The button input needs the same 1 kΩ + 100 nF filter as the limit switch, for
the same reason — motor cables induce spikes that look like presses.

---

# 7. The same sequence, host-played

If you'd rather keep the firmware as a dumb command server and drive this from
the PC like the 4-jaw demo, the whole sequence is:

```
Priming, once:
    SM2 OPEN                      (see caveat below)
    SM1 HOME

Loop:
    SM1 GOTO STEPS -10000         out to MAIN
    SM2 CLOSE                     close on the object
    SM1 GOTO STEPS 0              carry to HOME
    SM2 OPEN                      release
```

Four commands per cycle. Use the same player mechanics as the 4-jaw doc: wait
for each reply, 120 s timeout on moves and 60 s on grips, discard replies
carrying a stale run id, halt on any error.

**Caveat on the priming open:** `SM2 OPEN` is the *relative* open. If the jaws
were left clamped at power-off it will not move them. Either add a firmware
command that exposes `open_to_stop()`, or make sure the jaws are open before you
start the loop.

What you lose going this route: standalone operation, resume-after-power-loss,
and the button. What you save: the state store, phase dispatch, boot safety, and
pause plumbing — the large majority of the code.

---

# 8. Bring-up order

1. **SM1 alone** — direction, switch reads, homing repeatability, short moves.
   See `HANDOFF_SM1_AND_4JAW.md` §6.
2. **Find MAIN for your rig.** Jog out, read `sm1_pos` from `STATUS`. Don't
   assume `-10000`.
3. **Calibrate CLOSED.** Jog the jaws fully shut with nothing between them, send
   `SM2 MARK CLOSED`, confirm it appears in `STATUS` as `sm2_closed`.
4. **Test the two opens separately.** `SM2 OPEN` from a partly-closed position,
   then the open-to-stop path from a fully-clamped position. Confirm the second
   works when the tracked count is lying.
5. **One close on a real object.** Confirm it holds without crushing. Adjust the
   CLOSED position, not the current, to change grip firmness in position mode.
6. **Run one full cycle by hand**, command by command.
7. **Then let it loop.**

---

# 9. Differences from the 4-jaw demo, at a glance

| | 2-jaw | 4-jaw |
|---|---|---|
| Runs on | Pico, standalone | PC, command by command |
| Positions | HOME, MAIN | HOME, MAIN, REACH |
| Grip styles | Outside only | Outside and inside, alternating |
| Force feedback | Off — closes to position | Used on CLOSE and OPENGRIP |
| Commands per cycle | 4 | 13 |
| Survives power loss | Yes, resumes the phase | No |
| Needs a PC | No | Yes |
