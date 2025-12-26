import re
from lxml import etree

async def temperature(self, msg_data, create_config):
    if not msg_data or msg_data == '[]':
        self.logger.warning("Temperature parser: Received empty or invalid data")
        return

    tree = etree.HTML(msg_data)
    sensors = tree.xpath('.//span[@title]')

    if not sensors:
        self.logger.warning(f"Temperature parser: No <span title> elements found in HTML (length: {len(msg_data)} chars)")
        # Try alternative XPath patterns
        alt_sensors = tree.xpath('.//span[contains(@class, "temp") or contains(@class, "temperature")]')
        if alt_sensors:
            self.logger.info(f"Temperature parser: Found {len(alt_sensors)} sensors with alternative pattern")
            sensors = alt_sensors
        else:
            # Log sample of HTML to debug
            sample = msg_data[:500] if len(msg_data) > 500 else msg_data
            self.logger.warning(f"Temperature parser: No sensors found. HTML sample: {sample}")
            return
    else:
        self.logger.info(f"Temperature parser: Found {len(sensors)} temperature/fan sensors")

    sensors_published = 0
    for node in sensors:
        device_name = node.get('title')
        if not device_name:
            device_name = node.get('class', 'Unknown')

        device_value_raw = ''.join(node.itertext())
        device_value = ''.join(c for c in device_value_raw if c.isdigit() or c == '.')

        if device_value:
            if 'rpm' in device_value_raw.lower():
                device_name = re.sub('fan', '', device_name, flags=re.IGNORECASE).strip()
                device_value = int(device_value)
                payload = {
                    'name': f'Fan {device_name} Speed',
                    'unit_of_measurement': 'RPM',
                    'icon': 'mdi:fan',
                    'state_class': 'measurement'
                }
                self.logger.info(f"Publishing fan sensor: {device_name} = {device_value} RPM")
            else:
                device_value = float(device_value)
                payload = {
                    'name': f'{device_name} Temperature',
                    'unit_of_measurement': '°C',
                    'icon': 'mdi:thermometer',
                    'state_class': 'measurement',
                    'device_class': 'temperature'
                }
                self.logger.info(f"Publishing temperature sensor: {device_name} = {device_value}°C")

            self.mqtt_publish(payload, 'sensor', device_value, create_config=create_config)
            sensors_published += 1

    if sensors_published == 0:
        self.logger.warning(f"Temperature parser: No valid sensor data extracted from {len(sensors)} elements")
