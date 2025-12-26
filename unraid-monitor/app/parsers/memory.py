import json
import re


def _normalize_memory_label(label: str):
    label = label.strip().lower()
    if label in ('ram', 'memory'):
        return 'RAM'
    if label in ('flash', 'boot'):
        return 'Flash'
    if label in ('log', 'logs', 'syslog'):
        return 'Log'
    if label in ('docker', 'containers'):
        return 'Docker'
    return None


def _extract_labeled_percentages(text: str):
    cleaned = re.sub(r'<[^>]+>', ' ', text)
    pattern = re.compile(r'(RAM|Memory|Flash|Log|Logs|Syslog|Docker|Containers)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%', re.IGNORECASE)
    matches = pattern.findall(cleaned)
    labeled = {}
    for label, value in matches:
        normalized = _normalize_memory_label(label)
        if not normalized:
            continue
        labeled[normalized] = int(float(value))
    return labeled


def _parse_percent(value):
    if isinstance(value, (int, float)):
        return int(value) if 0 <= value <= 100 else None
    if isinstance(value, str):
        match = re.search(r'(\d+(?:\.\d+)?)\s*%', value)
        if match:
            return int(float(match.group(1)))
        if re.fullmatch(r'\d+(?:\.\d+)?', value):
            numeric = float(value)
            return int(numeric) if 0 <= numeric <= 100 else None
    return None


def _extract_named_ram_usage(parsed):
    names = parsed.get('name')
    ram = parsed.get('ram')
    if not isinstance(names, list) or not isinstance(ram, list):
        return {}
    percents = []
    for entry in ram:
        percent = _parse_percent(entry)
        if percent is not None:
            percents.append(percent)
    usage = {}
    for index, name in enumerate(names):
        if index >= len(percents):
            break
        usage[str(name)] = percents[index]
    return usage


def _extract_sys_usage(parsed):
    sys_entries = parsed.get('sys')
    if not isinstance(sys_entries, list):
        return []
    percents = []
    for entry in sys_entries:
        percent = None
        if isinstance(entry, (list, tuple)) and entry:
            percent = _parse_percent(entry[0])
        else:
            percent = _parse_percent(entry)
        if percent is not None:
            percents.append(percent)
    return percents


async def update1(self, msg_data, create_config):
    published_any = False

    parsed = None
    try:
        parsed = json.loads(msg_data)
    except Exception:
        parsed = None

    if isinstance(parsed, dict):
        ram_usage = _extract_named_ram_usage(parsed)
        if ram_usage:
            if 'System' in ram_usage:
                payload = {
                    'name': 'RAM Usage',
                    'unit_of_measurement': '%',
                    'icon': 'mdi:memory',
                    'state_class': 'measurement'
                }
                self.mqtt_publish(payload, 'sensor', ram_usage['System'], create_config=create_config, retain=True)
                published_any = True
            elif ram_usage:
                first_value = next(iter(ram_usage.values()))
                payload = {
                    'name': 'RAM Usage',
                    'unit_of_measurement': '%',
                    'icon': 'mdi:memory',
                    'state_class': 'measurement'
                }
                self.mqtt_publish(payload, 'sensor', first_value, create_config=create_config, retain=True)
                published_any = True

        sys_usage = _extract_sys_usage(parsed)
        sys_names = ['Flash', 'Log', 'Docker']
        for sys_name, sys_value in zip(sys_names, sys_usage):
            payload = {
                'name': f'{sys_name} Usage',
                'unit_of_measurement': '%',
                'icon': 'mdi:memory',
                'state_class': 'measurement'
            }
            self.mqtt_publish(payload, 'sensor', sys_value, create_config=create_config, retain=True)
            published_any = True

        if published_any:
            return

    memory_categories = ['RAM', 'Flash', 'Log', 'Docker']
    labeled = _extract_labeled_percentages(msg_data)
    matches = re.findall(r'(\d+(?:\.\d+)?\s*%)', msg_data)

    if labeled:
        for memory_name, memory_value in labeled.items():
            payload = {
                'name': f'{memory_name} Usage',
                'unit_of_measurement': '%',
                'icon': 'mdi:memory',
                'state_class': 'measurement'
            }
            self.mqtt_publish(payload, 'sensor', memory_value, create_config=create_config, retain=True)
            published_any = True
    else:
        for memory_name, memory_usage in zip(memory_categories, matches):
            memory_value = ''.join(c for c in memory_usage if c.isdigit())
            if memory_value:
                memory_value = int(memory_value)
                payload = {
                    'name': f'{memory_name} Usage',
                    'unit_of_measurement': '%',
                    'icon': 'mdi:memory',
                    'state_class': 'measurement'
                }
                self.mqtt_publish(payload, 'sensor', memory_value, create_config=create_config, retain=True)
                published_any = True

    if not published_any:
        self.logger.warning('[update1] No memory usage percentages found in payload')

    for fan_id, fan_rpm in enumerate(re.findall(r'(\d+)\s*RPM', msg_data)):
        fan_id += 1
        fan_name = f'Fan {fan_id}'
        fan_value = ''.join(c for c in fan_rpm if c.isdigit())
        if fan_value:
            fan_value = int(fan_value)
            payload = {
                'name': f'{fan_name} Speed',
                'unit_of_measurement': 'RPM',
                'icon': 'mdi:fan',
                'state_class': 'measurement'
            }
            self.mqtt_publish(payload, 'sensor', fan_value, create_config=create_config)
