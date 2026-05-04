# Factory Troubleshooting & Operations Manual

This is the standard knowledge base for diagnostic and repair operations. 
It defines station configurations, standard fault signatures (cascades), and safe repair procedures.

## 1. System Architecture & Station Signatures

The factory consists of two identical assembly lines (Line 1 and Line 2). Each line contains the following critical components:

*   **MC-A / MC-B (Machining Centers):** Responsible for milling and drilling raw materials. Contains high-speed spindles with bearings, temperature sensors, and VFD (Variable Frequency Drive) buses. 
    *   *ID Syntax:* `[1|2]A...` or `[1|2]B...` (e.g., `1Af1` = Line 1 Machining Center A spindle)
*   **Station 1 (Conveyor/Inspection):** Main belt motor cabinet, roller bearings, belt tension springs, and PSU terminals.
*   **Station 2 (Assembly):** Assembly stepper motors, pneumatic pressure lines, and gripper vacuum cups.
*   **Station 3 (Panel Positioner):** Cylinder rods and pneumatic clamps.
*   **Station 6 (Quality Control / Vision):** QC belt, CPU, LED lighting, and Vision camera lenses.
*   **Station 7 (Sorting):** Pivot bearings, sorting actuators, 5/2 valve springs.
*   **Station 8 (Transfer):** Grab vacuum lines.
*   **Station 9 (Warehouse):** Regen resistors, fork chain drives.

---

## 2. Common Fault Cascades & Root Cause Signatures

When diagnosing faults, look for these specific progression patterns to identify the root cause correctly.

### Scenario 1: Cooling System Failure (Thermal Cascade)
*   **Root Cause:** Chiller loses refrigerant affecting a single line.
*   **Progression:** 
    1. Machining center (MC-A/MC-B) spindle bearings warm up (preload shift). Spindle temperature rises.
    2. Machining centers drastically slow down (thermal compensation kicks in).
    3. Heat spreads to Station 1 belt motor cabinet.
    4. Station 2 steppers begin to miss steps due to heat. Gripper vacuum cups soften.
    5. QC Station (Station 6) CPU throttles (e.g. 85°C), dropping frame rates and causing focus drift (vision errors increase, pass rate drops).
*   **Signature:** Temperature rising sequentially downstream. Production drops on ONE line only. The opposite line remains perfectly healthy.

### Scenario 2: Contaminated Compressed Air (Pneumatic Collapse)
*   **Root Cause:** Air dryer desiccant saturates on one line, introducing moisture into the air supply.
*   **Progression:**
    1. Station 2 (Assembly) pneumatic pressure oscillates.
    2. Gripper vacuum seal time increases, eventually building double vacuum time.
    3. Station 3 positioner cylinder rods score and stick (jerky motion).
    4. Station 7 sorting valves weaken and stick.
    5. Gripper cups eventually tear, dropping products entirely.
*   **Signature:** Only pneumatic components (cylinders, grippers, valves, vacuums) fail. Failures cluster on a single line. All affected stations share the compressed air manifold.

### Scenario 3: Power Grid Instability
*   **Root Cause:** External voltage sags/spikes from the local grid.
*   **Progression:**
    1. VFD bus capacitor ripple rises on BOTH machining centers (Line 1 & Line 2 simultaneously).
    2. Station 1 PSU terminal resistance spikes on both lines.
    3. Station 6 (QC) LED drivers experience PWM faults; lighting flickers causing vision read errors on both lines.
    4. Sensor LEDs age/drift due to voltage stress.
    5. Warehouse regen resistors show bus ripple across both lines.
*   **Signature:** Perfectly symmetrical faults on BOTH lines occurring at the exact same time. Brownouts and voltage ripples affect multiple station types (VFDs, LEDs, PSUs).

### Scenario 4: End-of-Shift Mechanical Wear
*   **Root Cause:** Standard continuous production wear and tear. Chain reaction of debris and vibration.
*   **Progression:**
    1. Station 1 roller bearing defect (high vibration, e.g., 18mm/s).
    2. Station 1 belt tension drops due to spring fatigue.
    3. Debris and chatter from Station 1 misaligns products.
    4. Oil/debris contaminates downstream belts (Station 6), degrading sensor reflectors and coating vision lenses.
    5. Station 7 (Sorting) bearings break down and valve spools get contaminated.
*   **Signature:** Faults travel downstream step-by-step (1 -> 2 -> 3 -> 6 -> 7). Initiates with high vibration on Station 1. Opposite line remains healthy.

---

## 3. Repair Procedures & Safe Parameter Limits

When the **Repair Agent** proposes fixes to the operator, it MUST abide by these constraints. Any parameters outside these bounds will be rejected by the Validation Agent.

### 3.1 Resolving Thermal Issues (Cooling Failures)
*   **Action:** Reduce spindle speed to prevent bearing seizure. Enable auxiliary enclosure fans.
*   **Safe Bounds:**
    *   `spindle_speed`: 1000 RPM (min) to 4000 RPM (max). Default is usually 3000. Do NOT exceed 4000 RPM if temp > 50°C.
    *   `aux_fan_speed`: 0% to 100%. Set to 100% under thermal stress.

### 3.2 Resolving Pneumatic Issues (Moisture/Air Supply)
*   **Action:** Purge air lines, decrease cylinder actuation speeds to prevent seal blowouts, and adjust vacuum thresholds.
*   **Safe Bounds:**
    *   `system_pressure_setpoint`: 4.0 bar (min) to 7.0 bar (max). Nominal is 6.0 bar. 
    *   `actuator_speed`: 20% (min) to 100% (max). Drop to 50% during jerky movements.

### 3.3 Resolving Power Grid Issues
*   **Action:** Increase VFD smoothing parameters, lower overall line speed to reduce total draw, boost LED brightness to compensate for flicker.
*   **Safe Bounds:**
    *   `line_speed_multiplier`: 0.5 (min) to 1.0 (max). 
    *   `vfd_smoothing`: 0 (off) to 5 (max filtering).
    *   `camera_exposure_time`: 1ms to 20ms. Increase exposure if lighting is flickering.

### 3.4 Resolving Mechanical Wear/Debris
*   **Action:** Increase belt tension, activate automated lens air-wipers, slow down transfer arms.
*   **Safe Bounds:**
    *   `belt_tension`: 40% (min) to 90% (max). 
    *   `transfer_arm_speed`: 10% (min) to 80% (max). Reduce to 30% if pivot bearings are worn.

---
*Note: The Validation Agent will permanently FAIL any repair proposal that writes outside of the safe bounds listed above or attempts to bypass an active Emergency Stop.*