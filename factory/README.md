# Smart PLC Assistant - System Documentation

This README provides an overview of the core components in the `config`, `core`, `factory`, and `runners` directories. It also includes a detailed map of all Modbus inputs, coils (outputs), and registers used strictly in the factory operations.

## 📁 Directory Overview

### Config/

- **`config/mqtt_topics.py`**: MQTT Topic Definitions
- **`config/settings.py`**: Smart PLC Assistant — Configuration Settings
- **`config/__init__.py`**: Module logic and configuration.

### Core/

- **`core/llm_client.py`**: LLM Client Module
- **`core/mqtt_client.py`**: MQTT Client Module
- **`core/__init__.py`**: Module logic and configuration.

### Factory/

- **`factory/config.py`**: Factory Configuration
- **`factory/config_line2.py`**: Configuration for Assembly Line 2 (The Twin Line)
- **`factory/modbus_client.py`**: Modbus Client Wrapper
- **`factory/__init__.py`**: Factory Module
- **`factory/stations/machining.py`**: Machining Center Controllers — TV Assembly Production Line
- **`factory/stations/station1.py`**: Station 1: Chassis Loading & Inspection
- **`factory/stations/station2.py`**: Station 2: PCB Board Installation (Pick & Place)
- **`factory/stations/station3.py`**: Station 3: Display Panel Mounting
- **`factory/stations/station6.py`**: Station 6: Quality Control
- **`factory/stations/station7.py`**: Station 7: Sorting & Output
- **`factory/stations/transfer.py`**: Transfer Station: Product-to-Pallet Transfer
- **`factory/stations/warehouse.py`**: factory/stations/warehouse.py
- **`factory/stations/__init__.py`**: Station Controllers

### Runners/

- **`runners/fault scenarios.txt`**: Module logic and configuration.
- **`runners/how to start data logger`**: Module logic and configuration.
- **`runners/mqtt_data_logger.py`**: MQTT Sensor Data Logger — Saves sensor/telemetry data from each assembly line
- **`runners/realtime_aggregator.py`**: Real-Time Data Aggregator for AI Monitoring Agent
- **`runners/run_twin.py`**: Run Line 1 and Line 2 concurrently — WITH REAL FAULT INJECTION + MQTT TELEMETRY

## 🔌 Modbus Address Map

### 📥 Inputs

| Address | Source File | Station | IO Name | Description |
|---------|-------------|---------|---------|-------------|
| 0 | `factory/config.py` | Chassis Loading & Inspection | `sensor_entry` | Entry diffuse sensor |
| 1 | `factory/config.py` | Chassis Loading & Inspection | `sensor_station` | Station position sensor |
| 2 | `factory/config.py` | PCB Board Installation | `sensor_entry` | Entry diffuse sensor |
| 3 | `factory/config.py` | PCB Board Installation | `sensor_station` | Station position sensor (at blade) |
| 4 | `factory/config.py` | PCB Board Installation | `pp_moving_x` | P&P X axis in motion |
| 5 | `factory/config.py` | PCB Board Installation | `pp_moving_z` | P&P Z axis in motion |
| 6 | `factory/config.py` | PCB Board Installation | `pp_item_detected` | P&P gripper has item |
| 24 | `factory/config.py` | Machining Center A — Blue Base Producer | `is_busy` | Is Busy |
| 25 | `factory/config.py` | Machining Center A — Blue Base Producer | `has_error` | Has Error |
| 26 | `factory/config.py` | Machining Center A — Blue Base Producer | `opened` | Opened |
| 27 | `factory/config.py` | Machining Center A — Blue Base Producer | `exit_sensor` | Exit Sensor |
| 28 | `factory/config.py` | Machining Center B — Green Lid Producer | `is_busy` | Is Busy |
| 29 | `factory/config.py` | Machining Center B — Green Lid Producer | `has_error` | Has Error |
| 30 | `factory/config.py` | Machining Center B — Green Lid Producer | `opened` | Opened |
| 31 | `factory/config.py` | Machining Center B — Green Lid Producer | `exit_sensor` | Exit Sensor |
| 100 | `factory/config_line2.py` | Chassis Loading & Inspection (Line 2) | `sensor_entry` | Entry diffuse sensor |
| 101 | `factory/config_line2.py` | Chassis Loading & Inspection (Line 2) | `sensor_station` | Station position sensor |
| 102 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `sensor_entry` | Entry diffuse sensor |
| 103 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `sensor_station` | Station position sensor (at blade) |
| 104 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `pp_moving_x` | P&P X axis in motion |
| 105 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `pp_moving_z` | P&P Z axis in motion |
| 106 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `pp_item_detected` | P&P gripper has item |
| 107 | `factory/config_line2.py` | Display Panel Mounting (Line 2) | `pos_clamped` | Pos Clamped |
| 108 | `factory/config_line2.py` | Display Panel Mounting (Line 2) | `pos_limit` | Pos Limit |
| 109 | `factory/config_line2.py` | Display Panel Mounting (Line 2) | `sensor` | Sensor |
| 110 | `factory/config_line2.py` | Quality Control & Testing (Line 2) | `sensor_entry` | Sensor Entry |
| 111 | `factory/config_line2.py` | Sorting & Output (Line 2) | `sensor_entry` | Sensor Entry |
| 124 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `is_busy` | Is Busy |
| 125 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `has_error` | Has Error |
| 126 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `opened` | Opened |
| 127 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `exit_sensor` | Exit Sensor |
| 128 | `factory/config_line2.py` | Machining Center B — Green Lid Producer (Line 2) | `is_busy` | Is Busy |
| 129 | `factory/config_line2.py` | Machining Center B — Green Lid Producer (Line 2) | `has_error` | Has Error |
| 130 | `factory/config_line2.py` | Machining Center B — Green Lid Producer (Line 2) | `opened` | Opened |
| 131 | `factory/config_line2.py` | Machining Center B — Green Lid Producer (Line 2) | `exit_sensor` | Exit Sensor |

### 📤 Outputs (Coils)

| Address | Source File | Station | IO Name | Description |
|---------|-------------|---------|---------|-------------|
| 0 | `factory/config.py` | Chassis Loading & Inspection | `belt1` | Belt 1 (main) |
| 1 | `factory/config.py` | Chassis Loading & Inspection | `belt2` | Belt 1b (transition) |
| 2 | `factory/config.py` | Chassis Loading & Inspection | `emitter` | Emitter trigger |
| 3 | `factory/config.py` | Chassis Loading & Inspection | `stop_blade` | Stop blade UP/DOWN |
| 4 | `factory/config.py` | PCB Board Installation | `belt` | Station 2 belt |
| 5 | `factory/config.py` | PCB Board Installation | `stop_blade` | Stop blade 2 |
| 6 | `factory/config.py` | PCB Board Installation | `emitter` | Emitter 2 (Product Lid) |
| 7 | `factory/config.py` | PCB Board Installation | `pp_move_x` | P&P X axis move |
| 8 | `factory/config.py` | PCB Board Installation | `pp_move_z` | P&P Z axis move |
| 9 | `factory/config.py` | PCB Board Installation | `pp_grab` | P&P gripper |
| 40 | `factory/config.py` | Machining Center A — Blue Base Producer | `emitter` | Emitter |
| 41 | `factory/config.py` | Machining Center A — Blue Base Producer | `produce_lids` | Produce Lids |
| 42 | `factory/config.py` | Machining Center A — Blue Base Producer | `start` | Start |
| 43 | `factory/config.py` | Machining Center A — Blue Base Producer | `stop` | Stop |
| 44 | `factory/config.py` | Machining Center A — Blue Base Producer | `reset` | Reset |
| 45 | `factory/config.py` | Machining Center A — Blue Base Producer | `exit_belt` | Exit Belt |
| 46 | `factory/config.py` | Machining Center B — Green Lid Producer | `emitter` | Emitter |
| 47 | `factory/config.py` | Machining Center B — Green Lid Producer | `produce_lids` | Produce Lids |
| 48 | `factory/config.py` | Machining Center B — Green Lid Producer | `start` | Start |
| 49 | `factory/config.py` | Machining Center B — Green Lid Producer | `stop` | Stop |
| 50 | `factory/config.py` | Machining Center B — Green Lid Producer | `reset` | Reset |
| 100 | `factory/config_line2.py` | Chassis Loading & Inspection (Line 2) | `belt1` | Belt 1 (main) |
| 101 | `factory/config_line2.py` | Chassis Loading & Inspection (Line 2) | `belt2` | Belt 1b (transition) |
| 102 | `factory/config_line2.py` | Chassis Loading & Inspection (Line 2) | `emitter` | Emitter trigger |
| 103 | `factory/config_line2.py` | Chassis Loading & Inspection (Line 2) | `stop_blade` | Stop blade UP/DOWN |
| 104 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `belt` | Station 2 belt |
| 105 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `stop_blade` | Stop blade 2 |
| 106 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `emitter` | Emitter 2 (Product Lid) |
| 107 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `pp_move_x` | P&P X axis move |
| 108 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `pp_move_z` | P&P Z axis move |
| 109 | `factory/config_line2.py` | PCB Board Installation (Line 2) | `pp_grab` | P&P gripper |
| 111 | `factory/config_line2.py` | Display Panel Mounting (Line 2) | `belt` | Belt |
| 112 | `factory/config_line2.py` | Display Panel Mounting (Line 2) | `pos_raise` | Pos Raise |
| 113 | `factory/config_line2.py` | Display Panel Mounting (Line 2) | `pos_clamp` | Pos Clamp |
| 114 | `factory/config_line2.py` | Quality Control & Testing (Line 2) | `belt_3b` | Belt 3B |
| 115 | `factory/config_line2.py` | Quality Control & Testing (Line 2) | `belt` | Belt |
| 116 | `factory/config_line2.py` | Quality Control & Testing (Line 2) | `stop_blade` | Stop Blade |
| 117 | `factory/config_line2.py` | Quality Control & Testing (Line 2) | `light_green` | Light Green |
| 118 | `factory/config_line2.py` | Quality Control & Testing (Line 2) | `light_yellow` | Light Yellow |
| 119 | `factory/config_line2.py` | Quality Control & Testing (Line 2) | `light_red` | Light Red |
| 121 | `factory/config_line2.py` | Sorting & Output (Line 2) | `belt` | Belt |
| 122 | `factory/config_line2.py` | Sorting & Output (Line 2) | `sorter_turn` | Sorter Turn |
| 123 | `factory/config_line2.py` | Sorting & Output (Line 2) | `sorter_belt_fwd` | Sorter Belt Fwd |
| 124 | `factory/config_line2.py` | Sorting & Output (Line 2) | `sorter_belt_rev` | Sorter Belt Rev |
| 125 | `factory/config_line2.py` | Sorting & Output (Line 2) | `light_green` | Light Green |
| 126 | `factory/config_line2.py` | Sorting & Output (Line 2) | `light_red` | Light Red |
| 140 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `emitter` | Emitter |
| 141 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `produce_lids` | Produce Lids |
| 142 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `start` | Start |
| 143 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `stop` | Stop |
| 144 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `reset` | Reset |
| 145 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `exit_belt` | Exit Belt |
| 146 | `factory/config_line2.py` | Machining Center B — Green Lid Producer (Line 2) | `emitter` | Emitter |
| 147 | `factory/config_line2.py` | Machining Center B — Green Lid Producer (Line 2) | `produce_lids` | Produce Lids |
| 148 | `factory/config_line2.py` | Machining Center B — Green Lid Producer (Line 2) | `start` | Start |
| 149 | `factory/config_line2.py` | Machining Center B — Green Lid Producer (Line 2) | `stop` | Stop |
| 150 | `factory/config_line2.py` | Machining Center B — Green Lid Producer (Line 2) | `reset` | Reset |

### 🎛 Registers

| Address | Source File | Station | Name | Description |
|---------|-------------|---------|------|-------------|
| 1 | `factory/config.py` | Machining Center A — Blue Base Producer | `progress` | Progress Register |
| 2 | `factory/config.py` | Machining Center B — Green Lid Producer | `progress` | Progress Register |
| 10 | `factory/config_line2.py` | Quality Control & Testing (Line 2) | `vision_sensor` | Vision Sensor |
| 11 | `factory/config_line2.py` | Machining Center A — Blue Base Producer (Line 2) | `progress` | Progress Register |
| 12 | `factory/config_line2.py` | Machining Center B — Green Lid Producer (Line 2) | `progress` | Progress Register |
