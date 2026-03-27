# MQTT + Factory I/O Quick Start

## 1) Configure environment
1. Copy `.env.example` to `.env`.
2. Set your MQTT server values:
   - `MQTT_BROKER_HOST`
   - `MQTT_BROKER_PORT`
   - `MQTT_USERNAME` / `MQTT_PASSWORD` (if your broker requires auth)
3. Set Factory I/O Modbus values (default local):
   - `FACTORY_MODBUS_HOST=127.0.0.1`
   - `FACTORY_MODBUS_PORT=502`
   - `FACTORY_MODBUS_SLAVE_ID=1`

## 2) Prepare Factory I/O
1. Open your scene in Factory I/O.
2. Set driver to **Modbus TCP/IP Server**.
3. Keep host/port matching `.env` values.

## 3) Install dependencies
```powershell
pip install -r requirements.txt
```

## 4) Start bridge
```powershell
python -m factory.modbus_mqtt_bridge
```

The bridge will:
- Read Factory I/O sensors via Modbus
- Publish telemetry to MQTT topics under `factory/...`
- Subscribe to `factory/commands/#` and write commands back to Factory I/O

## 5) Quick MQTT checks
Subscribe:
```powershell
mosquitto_sub -h <broker_host> -p <broker_port> -t "factory/#" -v
```

Publish a command (example):
```powershell
mosquitto_pub -h <broker_host> -p <broker_port> -t "factory/commands/set_x" -m "{\"value\": 250}" 
```

## Common issues
- `Connection refused` on MQTT: broker not running, wrong host/port, or auth mismatch.
- Modbus connection fails: Factory I/O not running or wrong driver selected.
- No data appears: verify Factory I/O scene is active and addresses match expected mapping in `factory/modbus_mqtt_bridge.py`.
