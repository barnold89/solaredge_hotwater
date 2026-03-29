# SolarEdge Hot Water Controller

A custom Home Assistant integration for controlling and monitoring SolarEdge hot water heating elements (Heizstab) via the SolarEdge monitoring API.

## Features

- Monitor water temperature and active power consumption
- Control the heater operation mode (Auto / On / Off)
- Adjust power level via a slider (0–100%)
- View device status, schedule type, and auto-off reason
- Monitor PV surplus usage and communication status
- Configurable polling interval

## Requirements

- A SolarEdge account with access to the monitoring portal
- A SolarEdge site with a connected hot water controller (Load Device)
- Home Assistant 2024.1 or newer

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance.
2. Go to **Integrations** → click the three-dot menu → **Custom repositories**.
3. Add `https://github.com/barnold89/solaredge-hotwater` as an **Integration**.
4. Search for **SolarEdge Hot Water Controller** and install it.
5. Restart Home Assistant.

### Manual

1. Download or clone this repository.
2. Copy the `custom_components/solaredge_hotwater` folder into your Home Assistant `custom_components` directory.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **SolarEdge Hot Water Controller**.
3. Enter your SolarEdge **username**, **password**, and **Site ID**.
4. If multiple compatible devices are found, select the one you want to control.

The integration will automatically discover your hot water controller and create all entities.

### Options

After setup, you can adjust the polling interval via the integration's **Configure** button:

| Option | Default | Range |
|---|---|---|
| Polling interval (seconds) | 60 | 1 – 3600 |

## Entities

| Entity | Type | Description |
|---|---|---|
| Operation Mode | `select` | Control operation mode (auto / on / off) |
| Power Level | `number` | Set heater power (0–100%, only in manual mode) |
| Water Temperature | `sensor` | Current measured water temperature (°C) |
| Active Power | `sensor` | Current power consumption (W) |
| Rated Power | `sensor` | Device rated power (W) |
| Device Status | `sensor` | Current device status string |
| Schedule Type | `sensor` | Active schedule type |
| Auto Off Reason | `sensor` | Reason for automatic shutdown |
| Excess PV Enabled | `binary_sensor` | Whether PV surplus mode is active |
| Communication Status | `binary_sensor` | Whether the device is communicating |

## Finding your Site ID

Your Site ID is visible in the URL when you log in to the [SolarEdge monitoring portal](https://monitoring.solaredge.com):

```
https://monitoring.solaredge.com/solaredge-web/p/site/<SITE_ID>/dashboard
```

## Contributing

Pull requests and issue reports are welcome at [github.com/barnold89/solaredge-hotwater](https://github.com/barnold89/solaredge-hotwater).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
