# Handoff: SM1 platform axis + the 4-jaw demo sequence

Brief for an agent working in a **different repository** that has already built
the SM2 gripper axis and now needs the rest. Self-contained — no access to the
original repo is assumed. Every constant below is a real, tested value from a
rig that runs.

Hardware is identical: Pico 2W (MicroPython), TMC2208 on the platform axis,
TMC2209 on the gripper, same GPIOs.

---

# 1. What SM1 is

**SM1 is the platform axis.** It carries the whole gripper assembly back and
forth along one linear rail. The gripper (SM2) opens and closes; SM1 moves it
between pick and place positions. They are mechanically independent — SM1 does
not know or care what the jaws are doing.

Three positions matter, all measured in motor steps from HOME:

| Name | Value | What it is |
|---|---|---|
| `HOME` | `0` | Found **physically** by driving into a limit switch. Not a stored number. |
| `MAIN` | `-13000` | The far pick point. Negative = away from the switch. |
| `REACH` | `-7000` | Where the carriage parks at the end of each cycle. |

Everything away from HOME is tracked by counting steps — there is no encoder.
That count drifts slightly, which is why the sequence re-homes at the start and
why HOME is a physical switch rather than a remembered position.

---

# 2. SM1 circuit connections

## TMC2208 driver — standalone STEP/DIR mode, no UART

Unlike the TMC2209, SM1's driver has **no serial link**. The Pico cannot read or
configure it. It only pulses STEP and sets DIR. This is deliberate: SM1 needs no
StallGuard and no current control from software.

| Pico pin | GPIO | TMC2208 pin | Purpose |
|---|---|---|---|
| 24 | GP18 | `EN` | Enable, **active low**. Low = motor energised. |
| 25 | GP19 | `STEP` | One pulse = one microstep. |
| 26 | GP20 | `DIR` | Level sets direction. |
| 27 | GP21 | — | HOME limit switch (see below) |

Driver power:

| TMC2208 pin | Connect to |
|---|---|
| `VM` | 24 V motor supply |
| `GND` (both pins) | Ground |
| `VIO` | 3.3 V — take this from the **Pico's 3V3 OUT, pin 36** |
| `MS1`, `MS2` | **Leave unconnected** → 1/8 microstepping |
| `M1A`, `M1B` | Motor coil 1 |
| `M2A`, `M2B` | Motor coil 2 |
| `PDN`, `USART`, `CLK` | Leave unconnected |

**Keep each coil pair together.** `M1A`+`M1B` is one coil, `M2A`+`M2B` the
other. Splitting a pair across coils makes the motor hum and vibrate without
turning — a very common and confusing wiring mistake.

**MS1/MS2 floating gives 1/8 microstepping.** All step counts here assume that.
Change it and every number in this document rescales.

## Limit switch

```
GP21 ──┬── 1kΩ ──── switch ──── GND
       │
     100nF
       │
      GND
```

The switch is a plain mechanical contact between the pin and ground. Configure
GP21 as `Pin(21, Pin.IN, Pin.PULL_UP)` — the internal pull-up holds it high, and
closing the switch pulls it low. So **low = switch pressed**.

The 1 kΩ + 100 nF is not optional on a real rig. Motor cables radiate
interference, the switch wire runs beside them and picks it up as a voltage
spike, and a spike looks exactly like a switch press. This was observed on the
original build as random false triggers during motion. The filter needs ~0.1 ms
of steady voltage to respond: an induced spike lasts microseconds and is
ignored, a real press lasts tens of milliseconds and passes through. Software
debouncing does **not** fix this, because a strong spike looks like a clean edge.

**The switch must be on the CW side of travel** — homing drives CW into it.

## The direction inversion trap

On the original rig the motor coils were soldered in reverse, so commanding CW
produced physical ACW. Rather than resolder, the firmware inverts the DIR pin:

```python
SM1_INVERT_DIR = True   # set False for a normally-wired motor
```

Applied in the driver:

```python
def set_direction(self, direction):
    self.current_direction = int(direction)
    out = self.current_direction ^ 1 if self.invert_dir else self.current_direction
    self.dir_out.value(out)
```

**Check this on first power-up before anything else.** Jog SM1 a small amount and
confirm CW moves toward the limit switch. If it moves away, flip the flag. Do not
attempt to home until this is right — homing drives up to 200000 steps looking
for a switch it will never reach if the direction is wrong.

---

# 3. SM1 firmware

Three layers. Keep them separate; mixing them is what makes this hard to debug.

```
TMC2208     pulses pins. Knows nothing about position.
PlatformAxis   knows position, homing, chunked moves. Owns the step count.
command handler   parses serial text, calls PlatformAxis.
```

## Layer 1 — the driver

```python
class TMC2208:
    CW = 1
    ACW = 0

    SPEED_PRESETS_US = {"LOW": 1400, "MEDIUM": 900, "HIGH": 450}

    # No UART means no current control, so "torque" is approximated by
    # how gently the motion ramps up. Slower start = less chance of stalling.
    TORQUE_PRESETS = {
        "LOW":    {"start_us": 1800, "ramp_steps":  80, "run_limit_us": 1200},
        "MEDIUM": {"start_us": 1400, "ramp_steps": 160, "run_limit_us":  900},
        "HIGH":   {"start_us": 1100, "ramp_steps": 260, "run_limit_us":  600},
    }

    def enable(self):
        self.en_out.value(0)      # active low
        time.sleep_ms(25)         # driver needs time to energise

    def disable(self):
        self.en_out.value(1)

    def pulse(self, half_period_us):
        self.step_out.value(1)
        time.sleep_us(half_period_us)
        self.step_out.value(0)
        time.sleep_us(half_period_us)
```

Speed is expressed as the **half-period in microseconds** — smaller is faster.
A `pulse(450)` takes 900 µs total, so roughly 1100 steps/second.

## Layer 2 — homing

This is the subtlest part of SM1 and worth implementing exactly.

```python
def home(self, switch_read, should_pause=None):
    self.motor.enable()
    self._clear_switch(switch_read, HOMING_SLOW_US)     # 1
    if self._approach_switch(switch_read, HOMING_SPEED_US, should_pause) == "PAUSED":
        return False                                     # 2
    self.motor.set_direction(self.motor.ACW)             # 3
    for _ in range(HOMING_BACKOFF_STEPS):
        self.motor.pulse(HOMING_SPEED_US)
    if self._approach_switch(switch_read, HOMING_SLOW_US, should_pause) == "PAUSED":
        return False                                     # 4
    self.state["sm1_position_steps"] = 0                 # 5
    self.persist()
    return True
```

1. **Clear the switch first.** If the carriage is already resting on the switch,
   an approach would return "found it" having moved nothing — a false home at
   the wrong place. So back off ACW until the switch releases, plus
   `HOMING_BACKOFF_STEPS` of margin. Raise an error if it never releases: that
   means a stuck switch or inverted polarity, and continuing would be worse.
2. Fast approach CW until the switch trips.
3. Back off clear of it again.
4. **Slow re-approach.** A fast approach overshoots by a variable amount because
   the switch is detected between step pulses. Approaching slowly the second
   time makes HOME land in the same physical spot every run — typically within a
   step or two instead of tens.
5. Only now is position zero.

The approach ramps its speed:

```python
def _approach_switch(self, switch_read, speed_us, should_pause):
    self.motor.set_direction(self.motor.CW)
    steps = 0
    while True:
        if switch_read():
            return "TRIPPED"
        if steps < HOMING_RAMP_STEPS and HOMING_START_US > speed_us:
            cur_us = HOMING_START_US - (HOMING_START_US - speed_us) * steps // HOMING_RAMP_STEPS
        else:
            cur_us = speed_us
        self.motor.pulse(cur_us)
        steps += 1
        if steps >= HOMING_MAX_STEPS:
            raise RuntimeError("SM1 homing failed: switch never tripped after {} steps".format(steps))
        if should_pause is not None and should_pause():
            return "PAUSED"
```

**The ramp matters.** Commanding full homing speed from standstill stalls the
motor — it buzzes and never moves. Starting slow and accelerating over the first
few hundred steps fixes it. If it still stalls at t=0, raise `HOMING_START_US`.

Constants:

```python
HOMING_SPEED_US    = 900      # fast approach
HOMING_SLOW_US     = 1600     # slow re-approach
HOMING_MAX_STEPS   = 200000   # give up rather than grind forever
HOMING_BACKOFF_STEPS = 400
HOMING_START_US    = 2000     # ramp starts here
HOMING_RAMP_STEPS  = 300
```

## Layer 3 — moving to a position

```python
def move_to_absolute(self, target, should_pause=None):
    speed_us = self._speed_us()
    chunk = 100
    self.motor.enable()
    while True:
        current = self.state["sm1_position_steps"]
        remaining = target - current
        if remaining == 0:
            self.persist()
            return True
        direction = self.motor.CW if remaining > 0 else self.motor.ACW
        self.motor.set_direction(direction)
        step_count = min(chunk, abs(remaining))
        delta = 1 if direction == self.motor.CW else -1
        for _ in range(step_count):
            self.motor.pulse(speed_us)
            self.state["sm1_position_steps"] += delta
        if should_pause is not None and should_pause():
            self.persist()
            return False
```

Three decisions here were each learned by getting them wrong:

- **Enable once, outside the loop.** `enable()` sleeps 25 ms. Calling it per
  chunk inserts a 25 ms dead stop every 100 steps — the motor stutters and can
  lose position.
- **Save state only on exit, never per chunk.** Writing to flash mid-motion
  stalls the step train for milliseconds and produces visibly jerky movement.
- **Chunk at 100 steps** purely so `should_pause()` gets called often enough that
  a stop command interrupts within a fraction of a second instead of after the
  whole 13000-step move.

Position is updated **per step**, not per chunk, so an interrupted move still
leaves an accurate count.

---

# 4. The 4-jaw demo sequence

## How it is driven

**The PC plays this sequence, not the Pico.** The host sends one command, waits
for that command's reply, then sends the next. The firmware only needs to
implement individual actions — it holds no sequence logic at all.

This is much simpler to build than an on-device state machine, and it is the
right choice while the choreography is still changing.

## Positions used

```python
MAIN  = -13000     # far pick point
REACH =  -7000     # park position
HOME  =      0     # the limit switch
```

## The sequence

**Priming — once at the start:**

```
SM1 HOME          find the switch, zero the position
SM2 OPEN          open the jaws
```

**Then loop forever, alternating two pick styles:**

```
OUTSIDE pick — grab the tube from the outside, jaws close onto it
   1. SM1 GOTO STEPS -13000     go to MAIN with jaws open
   2. SM2 CLOSE                 close onto the tube  (force feedback)
   3. SM1 GOTO STEPS 0          carry it to HOME
   4. SM1 GOTO STEPS -13000     carry it back to MAIN
   5. SM2 OPEN                  release
   6. SM1 GOTO STEPS -7000      park at REACH

INSIDE pick — grab the tube from the inside, jaws expand against its wall
   1. SM2 CLOSE                 close the jaws so they fit inside the tube
   2. SM1 GOTO STEPS -13000     go to MAIN
   3. SM2 OPENGRIP              expand until they feel the wall  (force feedback)
   4. SM1 GOTO STEPS 0          carry to HOME
   5. SM1 GOTO STEPS -13000     carry back to MAIN
   6. SM2 CLOSE                 shrink the jaws to release
   7. SM1 GOTO STEPS -7000      park at REACH
```

One full cycle = one outside pick followed by one inside pick. Then it repeats.

**Only two steps use force feedback:** the `SM2 CLOSE` in step 2 of the outside
pick, and the `SM2 OPENGRIP` in step 3 of the inside pick. Those are the grabs.
The other `CLOSE`s in the inside pick are just positioning the jaws, and they
run to their mechanical limit and report "nothing held" — which is correct
there, not an error.

## The player loop

```python
def _exec_next(self, rid):
    if not self._running or rid != self._run_id:
        return                      # a stale reply from a stopped run
    if not self._queue:             # finished a full pass
        self.cycles += 1
        self._queue = list(self._body)
    cmd, timeout, match = self._queue.pop(0)
    self.send_expect(cmd, lambda ok, line: self._step_done(ok, line, rid),
                     match=match, timeout_ms=timeout)

def _step_done(self, ok, line, rid):
    if rid != self._run_id:
        return
    if not ok:
        self.stop("Demo STOPPED on error: " + line)
        return
    self._exec_next(rid)
```

Points that matter:

- **`_run_id` is incremented on every Run and Stop.** Replies carrying an old id
  are discarded. Without this, a reply arriving after Stop restarts the loop.
- **Any error halts the sequence.** Do not skip a failed step and continue —
  if a move failed, the position is now unknown and everything after it is wrong.
- **Timeouts: 120 s for moves, 60 s for grips.** A 13000-step move is genuinely
  slow. Too short a timeout aborts a perfectly good move.
- **Stop sends `ESTOP`**, which de-energises both drivers immediately and aborts
  a move already in progress.

## Reply matching — a real trap

Replies are matched to commands by looking for the command text in the reply.
`SM2 OPEN` and `SM2 OPENGRIP` collide: the string `"SM2 OPEN"` appears inside
`"OK SM2 OPENGRIP gripped=1 ..."`, so an `SM2 OPEN` command can be satisfied by
an `OPENGRIP` reply and the sequence desynchronises by one step.

Fix: match `SM2 OPEN` with an explicit trailing space, `"SM2 OPEN "`, and match
`OPENGRIP` on `"SM2 OPENGRIP"`.

---

# 5. Serial commands SM1 needs

Line-based text, `\n` terminated, 115200 baud. Replies start `OK ` or `ERR `.

| Command | Reply |
|---|---|
| `SM1 ENABLE` | `OK SM1 ENABLE` |
| `SM1 DISABLE` | `OK SM1 DISABLE` |
| `SM1 HOME` | `OK SM1 HOME homed=1 position=0` |
| `SM1 GOTO STEPS <n>` | `OK SM1 GOTO STEPS <n> position=<n>` |
| `SM1 JOG CW\|ACW <steps>` | `OK SM1 JOG completed=<n> position=<n>` |
| `SM1 SET SPEEDUS <us>\|AUTO` | `OK SM1 SET SPEEDUS <v>` |
| `SM1 SET SPEED\|TORQUE LOW\|MEDIUM\|HIGH` | `OK SM1 SET <name> <value>` |
| `ESTOP` | `OK ESTOP` — disables both drivers |
| `STATUS` | `OK STATUS sm1_pos=… sm1_enabled=… home_switch=… …` |

`homed=0` means the move was interrupted before reaching the switch — not an
error, but HOME was not established and the position is still unknown.

## Enable is a latch, and should be

Keep a persistent `sm1_enabled` flag. `HOME`, `JOG` and `GOTO` all refuse to run
unless it is set:

```python
def require_sm1_enabled():
    if not state.get("sm1_enabled", False):
        raise RuntimeError("SM1 is disabled - send SM1 ENABLE first")
```

Without this, any motion command that auto-enables the driver silently undoes a
Stop, and the axis moves when the operator believes it is disabled.

## Make ESTOP work mid-move

Motion functions take a `should_pause` callback, called between chunks, which
services incoming serial and reports whether to abort:

```python
def abort_when_disabled(enabled_key):
    def _should_pause():
        poll_serial()                              # handle any pending command
        return not state.get(enabled_key, True)    # aborted if disabled
    return _should_pause
```

Without this the Pico is deaf for the entire duration of a move, and ESTOP does
nothing until the move finishes on its own — which defeats the purpose.

---

# 6. Bring-up order

Do not attempt the full sequence first. In order:

1. **Direction.** `SM1 ENABLE`, then `SM1 JOG CW 200`. Confirm it moves *toward*
   the limit switch. If not, flip `SM1_INVERT_DIR`.
2. **Switch reads.** Poll `STATUS` and press the switch by hand. `home_switch`
   must change 0 → 1. If it never changes, check the pull-up and wiring.
3. **Homing.** `SM1 HOME`. It should approach fast, back off, re-approach slowly,
   and stop on the switch. Run it three times and confirm the carriage stops in
   the same physical place each time.
4. **Short moves.** `SM1 GOTO STEPS -1000`, then `SM1 GOTO STEPS 0`. Confirm it
   returns to the same spot.
5. **Find MAIN and REACH for your rig.** Jog out and read `sm1_pos` from
   `STATUS` at the positions you want. `-13000` and `-7000` are the original
   rig's numbers and will not match different mechanics.
6. **One outside pick, by hand**, one command at a time, watching each move.
7. **Then let the player loop run it.**

---

# 7. Things that cost time on the original build

- **Direction inverted.** Homing ran the full 200000 steps and errored. Check
  direction before anything else.
- **Motor stalls at the start of homing.** Fixed by the acceleration ramp. A
  stepper commanded to full speed from standstill just buzzes.
- **False home.** Carriage already touching the switch → instant "homed" without
  moving. Fixed by clearing the switch first.
- **Jerky motion.** Caused by re-enabling the driver and writing to flash inside
  the chunk loop. Enable once, save on exit.
- **Random limit-switch triggers during motion.** Electrical interference from
  the motor cables. Fixed by the RC filter, not by software.
- **Sequence desynchronised by one step.** `SM2 OPEN` matching an `OPENGRIP`
  reply. Fixed by the trailing space in the match string.
- **Stop did nothing until the move finished.** No `should_pause` callback
  threaded into the motion loop.
- **`MS1`/`MS2` change everything.** They set microstepping, and microstepping
  scales every step count. If MAIN suddenly needs a different number, check
  whether those pins changed state.

---

# 8. Summary for the agent picking this up

To finish the demo you need:

1. A `TMC2208` driver class — STEP/DIR/EN only, no UART, with `enable()`,
   `disable()`, `set_direction()` (honouring an invert flag) and `pulse()`.
2. A `PlatformAxis` class owning `sm1_position_steps`, with `home()` implemented
   as clear → fast approach → back off → slow approach → zero, and
   `move_to_absolute()` chunked at 100 steps with a `should_pause` callback.
3. Serial commands `SM1 ENABLE/DISABLE/HOME/JOG/GOTO STEPS`, plus `sm1_pos`,
   `sm1_enabled` and `home_switch` in `STATUS`.
4. A host-side player that sends the priming pair, then loops
   `outside + inside`, waiting for each reply, discarding stale replies by run
   id, and halting on any error.

The gripper side you already have is unchanged. SM1 does not interact with it —
the host sequence is the only thing that coordinates them.
