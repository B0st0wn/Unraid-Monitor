import re
import psutil
from utils import Preferences

async def cpu_temperature_avg(self, create_config):
    temps = psutil.sensors_temperatures()
    if not temps:
        return
    all_temps = [entry.current for chip in temps.values() for entry in chip if hasattr(entry, 'current')]
    if not all_temps:
        return
    avg_temp = round(sum(all_temps) / len(all_temps), 1)
    payload = {
        'name': 'CPU Temperature',
        'unit_of_measurement': '°C',
        'device_class': 'temperature',
        'icon': 'mdi:chip',
        'state_class': 'measurement'
    }
    self.mqtt_publish(payload, 'sensor', avg_temp, create_config=create_config, retain=True)

async def cpu_utilization(self, create_config):
    state_value = int(psutil.cpu_percent(interval=None))
    payload = {
        'name': 'CPU Utilization',
        'unit_of_measurement': '%',
        'icon': 'mdi:chip',
        'state_class': 'measurement'
    }
    self.mqtt_publish(payload, 'sensor', state_value, create_config=create_config)

async def cpuload(self, msg_data, create_config):
    state_value = None
    try:
        prefs = Preferences(msg_data)
        state_value = int(prefs.as_dict()['cpu']['host'])
    except Exception:
        match = re.search(r'(\d+(?:\.\d+)?)\s*%', msg_data)
        if match:
            state_value = int(float(match.group(1)))

    if state_value is None:
        state_value = int(psutil.cpu_percent(interval=None))
        self.logger.warning('[cpuload] Unable to parse CPU usage from payload; using psutil fallback')
    payload = {
        'name': 'CPU Utilization',
        'unit_of_measurement': '%',
        'icon': 'mdi:chip',
        'state_class': 'measurement'
    }
    self.mqtt_publish(payload, 'sensor', state_value, create_config=create_config)
