import time
import psutil

async def system_uptime(self, create_config):
    uptime_seconds = int(time.time() - psutil.boot_time())
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    pretty = f"{days}d {hours}h {minutes}m {seconds}s"

    payload = {
        'name': 'System Uptime',
        'icon': 'mdi:clock-outline',
        'state_class': 'measurement',
        'unit_of_measurement': 's'
    }

    attributes = { 'formatted': pretty }

    self.mqtt_publish(payload, 'sensor', uptime_seconds, json_attributes=attributes, create_config=create_config, retain=True)
