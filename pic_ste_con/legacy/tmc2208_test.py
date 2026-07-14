from tmc2208 import TMC2208

# Defaults are now STEP=GP19, DIR=GP20, EN=GP18 — no arguments needed
motor = TMC2208()

motor.move_with_presets(direction=TMC2208.CW, steps=6000, speed="HIGH", torque="MEDIUM")
motor.move_with_presets(direction=TMC2208.ACW, steps=3000, speed="MEDIUM", torque="LOW")
motor.disable()
