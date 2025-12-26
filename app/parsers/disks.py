import re
from utils import Preferences
from humanfriendly import parse_size

async def disks(self, msg_data, create_config):
    prefs = Preferences(msg_data)
    disks = prefs.as_dict()

    if not disks:
        self.logger.debug("No disk data received in message")
        return

    for n in disks:
        disk = disks[n]
        disk_name = disk['name']
        disk_temp = int(disk['temp']) if str(disk['temp']).isnumeric() else 0

        match = re.match(r'([a-z_]+)([0-9]+)', disk_name, re.I)
        if match:
            disk_num = match[2]
            disk_name = match[1] if match[1] != 'disk' else None
            disk_name = ' '.join(filter(None, [disk_name, disk_num]))
        disk_name = disk_name.title().replace('_', ' ')

        payload_temp = {
            'name': f'Disk {disk_name} Temperature',
            'unit_of_measurement': '°C',
            'device_class': 'temperature',
            'icon': 'mdi:harddisk',
            'state_class': 'measurement'
        }
        self.mqtt_publish(payload_temp, 'sensor', disk_temp, json_attributes=disk, create_config=create_config, retain=True)

        try:
            BYTES_PER_SECTOR = 1024
            BYTES_IN_TB = 1_000_000_000_000

            # Try multiple field name variations
            # Old WebSocket format: sizesb, fsused, fsfree (lowercase)
            # GraphQL format: sizesb, fsused, fsfree (converted from GraphQL)
            # Some versions may use camelCase: sizeSb, fsUsed, fsFree
            size_sb = disk.get('sizesb') or disk.get('sizeSb') or disk.get('size') or 0
            fs_used = disk.get('fsused') or disk.get('fsUsed') or 0
            fs_free = disk.get('fsfree') or disk.get('fsFree') or 0

            disk_size_tb = round((int(size_sb) * BYTES_PER_SECTOR) / BYTES_IN_TB, 2)
            disk_used_tb = round((int(fs_used) * BYTES_PER_SECTOR) / BYTES_IN_TB, 2)
            disk_free_tb = round((int(fs_free) * BYTES_PER_SECTOR) / BYTES_IN_TB, 2)
        except (ValueError, TypeError) as e:
            self.logger.debug(f"Error calculating disk sizes for {disk_name}: {e}")
            disk_size_tb = disk_used_tb = disk_free_tb = 0

        if disk_size_tb:
            payload_size = {
                'name': f'Disk {disk_name} Size',
                'unit_of_measurement': 'TB',
                'icon': 'mdi:database',
                'state_class': 'measurement'
            }
            self.mqtt_publish(payload_size, 'sensor', disk_size_tb, create_config=create_config, retain=True)
        if disk_used_tb:
            payload_used = {
                'name': f'Disk {disk_name} Used',
                'unit_of_measurement': 'TB',
                'icon': 'mdi:database-arrow-down',
                'state_class': 'measurement'
            }
            self.mqtt_publish(payload_used, 'sensor', disk_used_tb, create_config=create_config, retain=True)
        if disk_free_tb:
            payload_free = {
                'name': f'Disk {disk_name} Free',
                'unit_of_measurement': 'TB',
                'icon': 'mdi:database-arrow-up',
                'state_class': 'measurement'
            }
            self.mqtt_publish(payload_free, 'sensor', disk_free_tb, create_config=create_config, retain=True)
