#!/usr/bin/env python3
"""
Convert Home Assistant add-on options.json to config.yaml format
This allows main.py to work without modification
"""
import os
import json
import yaml


def convert_addon_config():
    """Read options.json and create config.yaml"""
    options_path = '/data/options.json'
    config_path = '/data/config.yaml'

    # Read add-on options
    with open(options_path, 'r') as f:
        options = json.load(f)

    # Build config structure matching current format
    config = {
        'unraid': [],
        'mqtt': {}
    }

    # Convert Unraid servers (array → array)
    for server in options.get('unraid_servers', []):
        unraid_config = {
            'name': server.get('name'),
            'host': server.get('host'),
            'port': server.get('port', 443),
            'ssl': server.get('ssl', True),
            'username': server.get('username'),
            'password': server.get('password'),
            'scan_interval': server.get('scan_interval', 30)
        }

        # Optional fields
        if server.get('api_key'):
            unraid_config['api_key'] = server.get('api_key')
        if server.get('ups_scan_interval'):
            unraid_config['ups_scan_interval'] = server.get('ups_scan_interval')
        if server.get('system_scan_interval'):
            unraid_config['system_scan_interval'] = server.get('system_scan_interval')

        config['unraid'].append(unraid_config)

    # Convert MQTT config with auto-discovery support
    mqtt_config = options.get('mqtt', {})

    # Auto-discovery: use environment variables set by run.sh
    if mqtt_config.get('auto_discover'):
        config['mqtt'] = {
            'host': os.getenv('MQTT_HOST', mqtt_config.get('host', 'core-mosquitto')),
            'port': int(os.getenv('MQTT_PORT', mqtt_config.get('port', 1883))),
            'username': os.getenv('MQTT_USER', mqtt_config.get('username', '')),
            'password': os.getenv('MQTT_PASS', mqtt_config.get('password', ''))
        }
    else:
        # Manual configuration
        config['mqtt'] = {
            'host': mqtt_config.get('host', 'core-mosquitto'),
            'port': mqtt_config.get('port', 1883),
            'username': mqtt_config.get('username', ''),
            'password': mqtt_config.get('password', '')
        }

    # Add base_topic if specified
    if mqtt_config.get('base_topic'):
        config['mqtt']['base_topic'] = mqtt_config.get('base_topic')

    # Write config.yaml
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    print(f"Configuration converted successfully")
    print(f"Monitoring {len(config['unraid'])} Unraid server(s)")
    print(f"MQTT broker: {config['mqtt']['host']}:{config['mqtt']['port']}")


if __name__ == '__main__':
    convert_addon_config()
