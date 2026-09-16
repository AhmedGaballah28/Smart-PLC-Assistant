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

**CRITICAL LAYOUT RULES:**
*   **Line Flow:** The physical flow of products from start to finish is: `Machining Centers (A & B) -> Station 1 -> Station 2 -> Station 3 -> Station 6 (QC) -> Station 7 (Sorting) -> Station 8 (Transfer) -> Station 9 (Warehouse)`.
*   **Non-existent Stations:** There is **NO Station 4** and **NO Station 5** in this factory. Any diagnostic assumption that refers to Station 4 or 5 is a hallucination and incorrect.
*   **Bottleneck Diagnosis:** If Station 3 is stuck in a `wait_downstream` state, the bottleneck is ALWAYS Station 6 (QC). You must diagnose and clear faults on Station 6, never Station 4.

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
    6. Sorting Station (Station 7) actuator seal expands, causing sluggish movement.
*   **Signature:** Temperature rising sequentially downstream. Production drops on ONE line only. The opposite line remains perfectly healthy.

### Scenario 2: Contaminated Compressed Air (Pneumatic Collapse)
*   **Root Cause:** Air dryer desiccant saturates on one line, introducing moisture into the air supply.
*   **Progression:**
    1. Station 2 (Assembly) pneumatic pressure oscillates.
    2. Gripper vacuum seal time increases, eventually building double vacuum time.
    3. Station 3 positioner cylinder rods score and stick (jerky motion).
    4. Station 7 sorting valves weaken and stick.
    5. Station 8 transfer grab vacuum line becomes restricted, limiting grip time.
    6. Station 2 Gripper cups eventually tear, dropping products entirely.
*   **Signature:** Only pneumatic components (cylinders, grippers, valves, vacuums) fail. Failures cluster on a single line. All affected stations share the compressed air manifold.

### Scenario 3: Power Grid Instability
*   **Root Cause:** External voltage sags/spikes from the local grid.
*   **Progression:**
    1. VFD bus capacitor ripple rises on BOTH machining centers (Line 1 & Line 2 simultaneously).
    2. Station 1 PSU terminal resistance spikes on both lines.
    3. Station 6 (QC) LED drivers experience PWM faults; lighting flickers causing vision read errors on both lines.
    4. Sensor LEDs age/drift due to voltage stress.
    5. Warehouse regen resistors show bus ripple across both lines.
    6. Sorting Station (Station 7) valve coils partially short from voltage spikes.
*   **Signature:** Perfectly symmetrical faults on BOTH lines occurring at the exact same time. Brownouts and voltage ripples affect multiple station types (VFDs, LEDs, PSUs).

### Scenario 4: End-of-Shift Mechanical Wear
*   **Root Cause:** Standard continuous production wear and tear. Chain reaction of debris and vibration.
*   **Progression:**
    1. Station 1 roller bearing defect (high vibration, e.g., 18mm/s).
    2. Station 1 belt tension drops due to spring fatigue.
    3. Debris and chatter from Station 1 misaligns products.
    4. Oil/debris contaminates downstream belts (Station 6), degrading sensor reflectors and coating vision lenses.
    5. Station 7 (Sorting) bearings break down and valve spools get contaminated.
    6. Warehouse Station (Station 9) fork chains stretch, hesitating during extension.
*   **Signature:** Faults travel downstream step-by-step (1 -> 2 -> 3 -> 6 -> 7 -> 9). Initiates with high vibration on Station 1. Opposite line remains healthy.

---

## 3. Repair Procedures & Safe Parameter Limits

When the **Repair Agent** proposes fixes to the operator, it MUST abide by these exact parameter constraints. The Python station controllers enforce these bounds directly via `apply_parameters`.
*   Note: Stations 6, 7, 8, and 9 do NOT physically apply these parameters, but to pass validation you **MUST** include at least one physical parameter (like `fan_speed` or `speed_factor`) alongside your `clear_fault` command to clear faults on those stations!

### 3.1 Resolving Thermal Issues (Cooling Failures)
*   **Action:** Reduce speed multiplier to lower heat generation, enable auxiliary cooling fans.
*   **Safe Bounds:**
    *   `fan_speed`: 0 to 100 (%). Set to 100 under thermal stress.
    *   `speed_factor`: 0.1 to 2.0 (Multiplier). Reduce to 0.5 under thermal stress.
    *   `spindle_speed`: 1000 to 4000 (RPM). Default is 3000. Do not exceed 4000 RPM.

### 3.2 Resolving Pneumatic Issues (Moisture/Air Supply)
*   **Action:** Adjust belt speeds to prevent product dropping during jerky cylinder movements.
*   **Safe Bounds:**
    *   `target_belt_speed`: 10 to 100 (%). Reduce to 50% during pneumatic oscillation.
    *   `speed_factor`: 0.1 to 2.0 (Multiplier). Drop to 0.8 to give seals more time to actuate.

### 3.3 Resolving Power Grid Issues
*   **Action:** Lower overall line speed to reduce total draw.
*   **Safe Bounds:**
    *   `speed_factor`: 0.1 to 2.0. Reduce to 0.5 during VFD ripple.
    *   `target_belt_speed`: 10 to 100. Reduce to 30.

### 3.4 Resolving Mechanical Wear/Debris
*   **Action:** Slow down belts and machine speeds to compensate for slip and vibration.
*   **Safe Bounds:**
    *   `target_belt_speed`: 10 to 100. 
    *   `speed_factor`: 0.1 to 2.0. Reduce to 0.5.

---
*Note: The Validation Agent will permanently FAIL any repair proposal that writes outside of the safe bounds listed above, invents fake parameter keys, or attempts to bypass an active Emergency Stop without sending a parameter along with `clear_fault`.*