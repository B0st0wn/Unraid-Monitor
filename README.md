# Unraid Monitor for Home Assistant

A Home Assistant add-on that integrates with your Unraid server by leveraging the GraphQL API to gather server data and forward it to Home Assistant via MQTT. Build powerful dashboards and automations for your Unraid server.

## Features

1. **Historical Monitoring** - Track CPU, RAM, network, disk temperatures, and more over time including disk spin-up patterns
2. **Automations** - Enable Unraid automations via Home Assistant with alerts for low disk space, high temperatures, and more
3. **Enhanced Disk Monitoring** - Visual disk array overview with color-coded status (grey for spun down, yellow/red for temperature warnings)
4. **Array Status** - Monitor array state, capacity usage, and parity disk health
5. **Docker & VM Monitoring** - Track running state, resource allocation, and container/VM status
6. **Share Management** - View which shares are on which disks and capacity utilization
7. **SMART Monitoring** - Get alerts for critical SMART attribute changes including SAS drives

## Requirements

- **Home Assistant** with Supervisor (for add-on support)
- **MQTT Broker** configured in Home Assistant (e.g., Mosquitto broker add-on)
- **Unraid 7.2.0+** with GraphQL API support
- **Unraid API Key** with Viewer role:
  - In Unraid: Settings → Management Access → API Keys → Create API Key
  - Name it (e.g., "Home Assistant") and select **Viewer** role
- **Unraid username and password** (still required for some legacy data sources)

## Installation

### Option 1: Add Repository (Recommended)

1. In Home Assistant, navigate to **Settings** → **Add-ons** → **Add-on Store**
2. Click the **⋮** menu (top-right) → **Repositories**
3. Add this repository URL: `[YOUR_REPOSITORY_URL]`
4. Find "Unraid Monitor" in the add-on store and click **Install**

### Option 2: Local Add-on

1. Copy the `unraid-monitor` folder to `/addons/` in your Home Assistant config directory
2. Refresh the Add-on Store page
3. Find "Unraid Monitor" under **Local add-ons** and click **Install**

## Configuration

After installation, configure the add-on with your Unraid server details:

```yaml
unraid_servers:
  - name: "My Unraid Server"
    host: "192.168.1.100"
    port: 443
    ssl: true
    username: "root"
    password: "YOUR_PASSWORD"
    api_key: "YOUR_API_KEY"
    scan_interval: 30
    ups_scan_interval: 30
    system_scan_interval: 30

mqtt:
  auto_discover: true
  host: "core-mosquitto"
  port: 1883
  username: ""
  password: ""
  base_topic: "unraid"

use_graphql: true
```

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `name` | Display name for your Unraid server | Required |
| `host` | IP address or hostname of Unraid server | Required |
| `port` | Port number (80 for HTTP, 443 for HTTPS) | 443 |
| `ssl` | Enable SSL/TLS connection | true |
| `username` | Unraid username (typically "root") | Required |
| `password` | Unraid password | Required |
| `api_key` | GraphQL API key with Viewer role | Required |
| `scan_interval` | Data collection interval (seconds) | 30 |
| `ups_scan_interval` | UPS data collection interval (seconds) | 30 |
| `system_scan_interval` | System data collection interval (seconds) | 30 |
| `mqtt.auto_discover` | Enable MQTT auto-discovery | true |
| `mqtt.host` | MQTT broker hostname | "core-mosquitto" |
| `mqtt.port` | MQTT broker port | 1883 |
| `mqtt.username` | MQTT username (if required) | "" |
| `mqtt.password` | MQTT password (if required) | "" |
| `mqtt.base_topic` | MQTT base topic for entities | "unraid" |
| `use_graphql` | Enable GraphQL API (required for Unraid 7.2+) | true |

## Usage

1. **Start the add-on** from the Info tab
2. **Check the logs** to ensure successful connection to Unraid and MQTT
3. **View devices** in Home Assistant: Settings → Devices & Services → MQTT
4. Your Unraid server should appear as a device with multiple entities

## Available Sensors

The add-on creates sensors for:

- **CPU** - Usage percentage, temperature, and load metrics
- **Memory** - Usage, available, and percentage
- **Network** - Upload/download rates and totals
- **Disks** - Temperature, size, used/free space, and SMART status
- **Array** - State, capacity usage, and usage percentage
- **Parity** - Status, temperature, and size for each parity disk
- **Docker Containers** - Running state, image, ports, and auto-start status
- **Virtual Machines** - Running state, vCPU count, and memory allocation
- **UPS** - Power status, battery level, runtime (if UPS is connected)
- **GPU** - Load, memory usage, fan speed, power, temperature (via GPU Stats plugin)
- **Coral TPU** - Temperature, throttle status, device presence (requires setup - see below)
- **System** - Uptime with formatted display

## Lovelace Dashboard

Example Lovelace cards and templates are available in the `lovelace` folder.

### Required Custom Cards

- [button-card](https://github.com/custom-cards/button-card)
- [vertical-stack-in-card](https://github.com/ofekashery/vertical-stack-in-card)
- [auto-entities](https://github.com/thomasloven/lovelace-auto-entities)
- [card-mod](https://github.com/thomasloven/lovelace-card-mod)

### Setup

1. Copy button-card templates from `/lovelace/templates/` to `/config/lovelace/templates/button_card/`:
   - `network_share.yaml`
   - `simple_bar.yaml`
   - `unraid_disk.yaml`

2. Add to your `ui-lovelace.yaml`:
   ```yaml
   button_card_templates: !include_dir_merge_named lovelace/templates/button_card
   ```

3. Use the example cards from `lovelace/example.yaml` as a starting point

## Advanced Features

### SMART Monitoring Package

The `packages` folder includes:
- **UnRaid Smart Data** - Caches SMART attributes for all disks
- **Notify on SMART Attribute Change** - Sends notifications when critical SMART attributes change
- Particularly useful for SAS drives where Unraid doesn't provide native SMART notifications

### Multiple Servers

You can monitor multiple Unraid servers by adding additional entries to the `unraid_servers` list in the configuration.

### Coral TPU Monitoring

Monitor Google Coral Edge TPU accelerators (PCIe/M.2 or USB) installed in your Unraid server. This requires installing a small PHP script on the Unraid server.

#### Supported Devices

| Device Type | Temperature | Throttle Status | Presence |
|-------------|-------------|-----------------|----------|
| PCIe/M.2 Coral | Yes | Yes | Yes |
| USB Coral | No (hardware limitation) | No | Yes |

#### Installation

1. **SSH into your Unraid server**

2. **Create the plugin directory and script:**
   ```bash
   mkdir -p /usr/local/emhttp/plugins/coral
   nano /usr/local/emhttp/plugins/coral/coral_status.php
   ```

3. **Paste the contents of `extras/coral_status.php`** from this repository

4. **Save and exit** (Ctrl+X, Y, Enter in nano)

5. **Test the endpoint** by visiting in your browser:
   ```
   https://YOUR_UNRAID_IP/plugins/coral/coral_status.php
   ```

   You should see JSON output like:
   ```json
   {
     "pcie": [
       {
         "id": "apex_0",
         "device": "/dev/apex0",
         "temp": 45000,
         "temp_c": 45,
         "throttle_state": "normal"
       }
     ],
     "usb": [],
     "summary": {
       "total_devices": 1,
       "pcie_count": 1,
       "usb_count": 0
     }
   }
   ```

6. **Restart the Unraid Monitor add-on** - the Coral TPU sensors will appear automatically

#### Sensors Created

For **PCIe/M.2 Coral TPU**:
- `Coral TPU 0 Temperature` - Current temperature in °C
- `Coral TPU 0 Status` - Throttle state (Normal, Throttled 250 MHz, Throttled 125 MHz, etc.)
- `Coral TPU 0` - Presence binary sensor

For **USB Coral TPU**:
- `Coral USB 0` - Presence binary sensor
- `Coral USB 0 Initialized` - Whether the TPU has been accessed by an application

Summary:
- `Coral TPU Count` - Total number of Coral devices detected

#### Making the Script Persistent

The script will be lost after an Unraid reboot. To make it persistent:

1. **Using User Scripts plugin** (recommended):
   - Install the "User Scripts" plugin from Community Applications
   - Create a new script that runs "At First Array Start Only"
   - Add the commands to create the directory and copy the script

2. **Using the Go file**:
   Add to `/boot/config/go`:
   ```bash
   mkdir -p /usr/local/emhttp/plugins/coral
   cp /boot/config/plugins/coral/coral_status.php /usr/local/emhttp/plugins/coral/
   ```

   And save the PHP file to `/boot/config/plugins/coral/coral_status.php` (flash drive persists across reboots)

#### Troubleshooting Coral TPU

**No sensors appearing:**
- Check add-on logs for: `Coral TPU: no working endpoint found`
- Verify the PHP script is accessible at the URL above
- Ensure the Coral driver is installed (check for `/dev/apex0` or `lsusb` showing Coral device)

**Temperature showing 0 or missing:**
- USB Coral TPUs do not have temperature sensors (hardware limitation)
- For PCIe, check that `/sys/class/apex/apex_0/temp` exists and is readable

**Verify Coral is detected on Unraid:**
```bash
# For PCIe Coral
ls -la /sys/class/apex/
cat /sys/class/apex/apex_0/temp

# For USB Coral
lsusb | grep -E "1a6e:089a|18d1:9302"
```

## Troubleshooting

### Add-on won't start
- Check the add-on logs for error messages
- Verify your Unraid API key is valid and has Viewer role
- Ensure MQTT broker is running and accessible

### No entities appearing in Home Assistant
- Verify MQTT integration is configured in Home Assistant
- Check that `mqtt.auto_discover` is set to `true`
- Restart the add-on and check logs for MQTT connection errors

### Temperature sensors showing 0°C
- Some devices (like flash drives) don't have temperature sensors
- The add-on now skips creating sensors for devices without valid temperatures

### VM specs not showing
- VM vCPU and memory data requires HTTP access to VMMachines.php
- Verify username/password are correct
- Check add-on logs for HTTP connection errors

## Updating

When updating to a new version, it's recommended to:

1. Delete the MQTT device in Home Assistant (Settings → Devices & Services → MQTT)
2. Restart the add-on
3. The device will be recreated with the latest sensor configuration

This prevents duplicate or renamed entities from accumulating.

## Version History

- **2.3.x** - Added array state, parity monitoring, system uptime, disk size sensors
- **2.2.x** - Added disk capacity sensors (size, used, free in TB)
- **2.1.x** - Added Docker and VM monitoring
- **2.0.x** - Initial Home Assistant add-on release with GraphQL support

## Contributing

Issues, pull requests, and suggestions are welcome! If you find this useful, please consider starring the repository.

## Support

If you encounter issues:
1. Check the add-on logs
2. Review the troubleshooting section
3. Open an issue on GitHub with logs and configuration details

## Credits

Based on the original [hass-unraid](https://github.com/idmedia/hass-unraid) project, adapted for Home Assistant add-on architecture with GraphQL API support for Unraid 7.2+.

## License

MIT License - see LICENSE file for details
