# Unraid Monitor - Home Assistant Add-on

Monitor your Unraid server(s) and publish metrics to Home Assistant via MQTT.

## Features

- **GraphQL Mode** (Unraid 7.2+): Modern API with comprehensive data
- **WebSocket Mode** (Legacy): Fallback for older Unraid versions
- **Multi-Server Support**: Monitor multiple Unraid servers from one add-on
- **MQTT Auto-Discovery**: Automatically finds and uses HA's Mosquitto broker
- **Real-time Monitoring**: Docker containers, VMs, disks, array status, UPS, and more
- **Customizable Refresh Rates**: Separate intervals for UPS and system metrics

## Installation

### 1. Add Custom Repository

1. Navigate to **Settings → Add-ons → Add-on Store**
2. Click the three dots (⋮) in the top right
3. Select **Repositories**
4. Add this repository URL:
   ```
   https://github.com/B0st0wn/hass-unraid
   ```
5. Click **Add** and refresh the page

### 2. Install the Add-on

1. Find "Unraid Monitor" in the Add-on Store
2. Click on it and press **Install**
3. Wait for installation to complete

### 3. Configure

Click on the **Configuration** tab and add your Unraid server details:

```yaml
unraid_servers:
  - name: My Unraid Server
    host: 192.168.1.100
    port: 443
    ssl: true
    username: root
    password: your_password_here
    api_key: your_api_key_here
    scan_interval: 30
    ups_scan_interval: 15
    system_scan_interval: 15

mqtt:
  auto_discover: true
  base_topic: unraid

use_graphql: true
```

### 4. Generate Unraid API Key (for GraphQL mode)

1. Open Unraid WebGUI
2. Go to **Settings → Management Access**
3. Scroll to **API Keys** section
4. Click **Generate API Key**
5. Name it "Home Assistant"
6. Copy the key to add-on configuration (`api_key` field)

### 5. Start the Add-on

1. Go to the **Info** tab
2. Click **Start**
3. Enable **Start on boot** and **Watchdog** (recommended)
4. Check the **Log** tab for any errors

### 6. Verify in Home Assistant

1. Go to **Settings → Devices & Services → MQTT**
2. You should see a device for each Unraid server
3. Entities will appear for:
   - Docker containers (binary sensors for running/stopped state)
   - Virtual machines (binary sensors + vCPU/memory sensors)
   - Disks (temperature, usage, status)
   - Array status and usage
   - Shares (usage percentage)
   - UPS (battery, load, runtime)
   - System metrics (CPU, RAM, temperatures, fans)

## Configuration Options

### Unraid Server Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `name` | Yes | - | Display name for the server |
| `host` | Yes | - | IP or hostname of Unraid server |
| `port` | No | 443 | HTTPS port |
| `ssl` | No | true | Use HTTPS |
| `username` | Yes | - | Unraid username (usually 'root') |
| `password` | Yes | - | Unraid password |
| `api_key` | Conditional | - | API key for GraphQL (required if `use_graphql=true`) |
| `scan_interval` | No | 30 | General scan interval (seconds) |
| `ups_scan_interval` | No | 15 | UPS data refresh rate (seconds, 10-15 for real-time) |
| `system_scan_interval` | No | 15 | System metrics refresh rate (seconds, 10-15 for real-time) |

### MQTT Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `auto_discover` | No | true | Auto-detect HA's Mosquitto add-on |
| `host` | Conditional | core-mosquitto | MQTT broker hostname (required if auto_discover=false) |
| `port` | Conditional | 1883 | MQTT broker port (required if auto_discover=false) |
| `username` | Conditional | - | MQTT username (required if auto_discover=false) |
| `password` | Conditional | - | MQTT password (required if auto_discover=false) |
| `base_topic` | No | unraid | MQTT topic prefix |

**MQTT Auto-Discovery:**
- When `auto_discover: true`, the add-on automatically finds and uses HA's Mosquitto add-on
- No need to configure MQTT credentials manually
- If Mosquitto add-on is not found, it falls back to manual configuration

### Global Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `use_graphql` | No | true | Use GraphQL API (Unraid 7.2+) or WebSocket (legacy) |

## Multiple Unraid Servers

To monitor multiple servers, add additional entries to `unraid_servers`:

```yaml
unraid_servers:
  - name: Main Server
    host: 192.168.1.100
    username: root
    password: password1
    api_key: key1

  - name: Backup Server
    host: 192.168.1.101
    username: root
    password: password2
    api_key: key2
```

Each server will appear as a separate device in Home Assistant.

## Sensors Published

The add-on creates the following entities for each Unraid server:

### Docker Containers
- `binary_sensor.{server}_docker_{container}_state` - Running/stopped state
- Attributes: container ID, image, status, auto-start, port mappings

### Virtual Machines
- `binary_sensor.{server}_vm_{name}_state` - Running/stopped/paused state
- `sensor.{server}_vm_{name}_vcpus` - Virtual CPU count
- `sensor.{server}_vm_{name}_memory` - Memory allocation (MB)
- Attributes: UUID, architecture, emulator

### Disks
- `sensor.{server}_disk_{name}_temperature` - Disk temperature
- `sensor.{server}_disk_{name}_usage` - Disk usage percentage
- `sensor.{server}_disk_{name}_size` - Total disk size
- Attributes: device path, filesystem type, status

### Array & Parity
- `sensor.{server}_array_state` - Array state (STARTED, STOPPED, etc.)
- `sensor.{server}_array_usage` - Array usage percentage
- `sensor.{server}_parity_{name}_status` - Parity disk status
- Attributes: total/used/free space in TB

### Shares
- `sensor.{server}_share_{name}_usage` - Share usage percentage
- Attributes: size/used/free in GB, allocator, cache settings

### UPS (if available)
- `sensor.{server}_ups_battery` - Battery level (%)
- `sensor.{server}_ups_load` - Load percentage
- `sensor.{server}_ups_load_power` - Load power (W)
- `sensor.{server}_ups_runtime` - Estimated runtime (minutes)
- `sensor.{server}_ups_status` - UPS status

### System
- `sensor.{server}_cpu_temperature` - CPU temperature
- `sensor.{server}_cpu_utilization` - CPU usage %
- `sensor.{server}_ram_usage` - RAM usage %
- `sensor.{server}_flash_usage` - Flash drive usage %
- `sensor.{server}_system_uptime` - Server uptime
- `sensor.{server}_fan_{name}_speed` - Fan speeds
- `sensor.{server}_{component}_temperature` - Component temperatures

### Connectivity
- `binary_sensor.{server}_connectivity` - Online/offline status

## Troubleshooting

### Add-on won't start

**Check logs:**
1. Go to Add-on → Log tab
2. Look for error messages

**Common issues:**
- Unraid server unreachable from HA network
- Incorrect credentials (username/password)
- Invalid API key or API key expired
- MQTT broker not running (if auto_discover=false)

### No entities appearing in HA

**Verify MQTT:**
1. Ensure Mosquitto MQTT broker add-on is installed and running
2. Go to Settings → Devices & Services → MQTT
3. Check if MQTT integration is configured

**Check add-on logs:**
- Look for "Successfully connected to mqtt server" message
- Look for sensor publishing messages

### GraphQL errors

**Requirements:**
- Unraid version must be 7.2 or higher
- Valid API key configured
- API key hasn't been deleted or expired

**Solution:**
1. Verify Unraid version in WebGUI
2. Generate a new API key
3. Set `use_graphql: false` to use legacy WebSocket mode

### MQTT auto-discovery not working

**Ensure:**
1. Mosquitto add-on is installed and started
2. `auto_discover: true` in configuration
3. Add-on has been restarted after changing config

**Fallback:**
1. Set `auto_discover: false`
2. Manually configure MQTT broker details:
   ```yaml
   mqtt:
     auto_discover: false
     host: core-mosquitto
     port: 1883
     username: your_mqtt_user
     password: your_mqtt_password
   ```

### UPS/System metrics not updating

**Check refresh intervals:**
- `ups_scan_interval` should be 15-30 seconds for real-time updates
- `system_scan_interval` should be 15-30 seconds for real-time updates

**For fastest updates (10-15 seconds):**
```yaml
unraid_servers:
  - name: My Server
    # ... other config ...
    ups_scan_interval: 15
    system_scan_interval: 15
```

### Connectivity sensor showing "Unknown"

This typically happens on first startup. The sensor should show "ON" after the add-on successfully connects to MQTT.

**If it persists:**
1. Restart the add-on
2. Check MQTT broker is running
3. Check add-on logs for connection errors

## Support

For issues, questions, or feature requests:
- GitHub Issues: https://github.com/B0st0wn/hass-unraid/issues
- Home Assistant Community: https://community.home-assistant.io/

## Advanced: Manual MQTT Configuration

If you're using an external MQTT broker (not HA's Mosquitto add-on):

```yaml
mqtt:
  auto_discover: false
  host: mqtt.example.com
  port: 1883
  username: my_mqtt_user
  password: my_mqtt_password
  base_topic: unraid
```

## Credits

Based on the original hass-unraid project with GraphQL support and Home Assistant add-on conversion.
