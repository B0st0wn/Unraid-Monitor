import re
from humanfriendly import parse_size

async def parity(self, msg_data, create_config):
    data = msg_data.split(';')
    if len(data) < 5:
        return

    position_size = re.sub(r'\([^)]*\)', '', data[2])
    position_pct = data[2][data[2].find('(') + 1:data[2].find(')')]
    position_pct = ''.join(c for c in position_pct if c.isdigit() or c == '.')
    try:
        state_value = float(position_pct)
    except ValueError:
        state_value = 0.0

    payload = {
        'name': 'Parity Check',
        'unit_of_measurement': '%',
        'icon': 'mdi:database-eye',
        'state_class': 'measurement'
    }

    json_attributes = {
        'total_size': parse_size(data[0]),
        'elapsed_time': data[1],
        'current_position': parse_size(position_size),
        'estimated_speed': parse_size(data[3]),
        'estimated_finish': data[4]
    }

    if len(data) > 5:
        json_attributes['sync_errors_corrected'] = data[5]

    self.mqtt_publish(payload, 'sensor', state_value, json_attributes=json_attributes, create_config=create_config)

    valid = "ON" if state_value >= 100 else "OFF"
    payload_valid = {
        'name': 'Parity Validity',
        'device_class': 'safety'
    }
    self.mqtt_publish(payload_valid, 'binary_sensor', valid, json_attributes={'parity_progress': state_value}, create_config=create_config)
