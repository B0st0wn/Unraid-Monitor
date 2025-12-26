import re
from lxml import etree

async def temperature(self, msg_data, create_config):
    tree = etree.HTML(msg_data)
    sensors = tree.xpath('.//span[@title]')
    for node in sensors:
        device_name = node.get('title')
        device_value_raw = ''.join(node.itertext())
        device_value = ''.join(c for c in device_value_raw if c.isdigit() or c == '.')
        if device_value:
            if 'rpm' in device_value_raw:
                device_name = re.sub('fan', '', device_name, flags=re.IGNORECASE).strip()
                device_value = int(device_value)
                payload = {
                    'name': f'Fan {device_name} Speed',
                    'unit_of_measurement': 'RPM',
                    'icon': 'mdi:fan',
                    'state_class': 'measurement'
                }
            else:
                device_value = float(device_value)
                payload = {
                    'name': f'{device_name} Temperature',
                    'unit_of_measurement': '°C',
                    'icon': 'mdi:thermometer',
                    'state_class': 'measurement',
                    'device_class': 'temperature'
                }
            self.mqtt_publish(payload, 'sensor', device_value, create_config=create_config)
