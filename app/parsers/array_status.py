# parsers/array_status.py
import re
import html
import json


def _normalize_disk_name(disk_name: str) -> str:
    match = re.match(r'([a-z_]+)([0-9]+)', disk_name, re.I)
    if match:
        disk_num = match[2]
        disk_name = match[1] if match[1] != 'disk' else None
        disk_name = ' '.join(filter(None, [disk_name, disk_num]))
    return str(disk_name).title().replace('_', ' ')


def _extract_disk_stats(html_data: str):
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_data, re.S)
    for row in rows:
        name_match = re.search(r"Device\?name=([^\"'&]+)", row)
        if not name_match:
            continue
        raw_name = name_match.group(1)
        disk_name = _normalize_disk_name(raw_name)

        stripped = re.sub(r"<[^>]+>", " ", row)
        stripped = stripped.replace("\xb0", "C").replace("\u2009", " ")
        temp_match = re.search(r"(\d+(?:\.\d+)?)\s*C", stripped)
        temp_value = None
        if temp_match:
            temp_value = float(temp_match.group(1))
            if temp_value <= 0 or temp_value > 150:
                temp_value = None

        load_match = re.search(r"load'>\s*(\d+(?:\.\d+)?)\s*%<", row)
        load_value = None
        if load_match:
            load_value = int(float(load_match.group(1)))

        yield disk_name, temp_value, load_value

async def array_status(self, msg_data, create_config):
    try:
        parsed = json.loads(msg_data)
        if not isinstance(parsed, dict) or not parsed.get('disk'):
            return
        html_data = html.unescape(parsed['disk'][0])

        match_text = re.search(r"id=['\"]text-parity['\"]>(\w+)<", html_data)
        match_orb = re.search(r"fa fa-circle orb (\w+-orb)", html_data)

        if match_text:
            state = match_text.group(1).capitalize()
        elif match_orb:
            orb = match_orb.group(1)
            state = "Healthy" if "green" in orb else "Error" if "red" in orb else "Unknown"
        else:
            state = "Unknown"

        payload = {
            "name": "Array",
            "icon": "mdi:server"
        }

        self.mqtt_publish(payload, "sensor", state, create_config=create_config)

        for disk_name, temp_value, load_value in _extract_disk_stats(html_data):
            if temp_value is not None:
                payload_temp = {
                    "name": f"Disk {disk_name} Temperature",
                    "unit_of_measurement": "C",
                    "device_class": "temperature",
                    "icon": "mdi:harddisk",
                    "state_class": "measurement",
                }
                self.mqtt_publish(payload_temp, "sensor", round(temp_value, 1), create_config=create_config, retain=True)

            if load_value is not None:
                payload_load = {
                    "name": f"Disk {disk_name} Load",
                    "unit_of_measurement": "%",
                    "icon": "mdi:gauge",
                    "state_class": "measurement",
                }
                self.mqtt_publish(payload_load, "sensor", load_value, create_config=create_config, retain=True)

    except Exception:
        self.logger.exception("[array_status] Failed to parse array health")
