import re
from lxml import etree
from utils import normalize_str

async def vms(self, msg_data, create_config):
    tree = etree.HTML(msg_data)
    vm_rows = tree.xpath('//tr[contains(@class, "sortable")]')

    for index, row in enumerate(vm_rows):
        name = ''.join(row.xpath('.//span[@class="inner"]/a/text()')).strip()
        if not name:
            continue

        vm_id = normalize_str(name)
        state = ''.join(row.xpath('.//span[@class="state"]/text()')).strip().lower()
        power = 'ON' if 'started' in state or 'running' in state else 'OFF'

        vcpu_text = ''.join(row.xpath(f'.//a[contains(@class, "vcpu-")]/text()')).strip()
        try:
            vcpus = int(vcpu_text)
        except ValueError:
            vcpus = 0

        mem_text = ''.join(row.xpath('./td[4]/text()')).strip()
        mem_mb = int(re.sub(r'[^\d]', '', mem_text)) if mem_text else 0

        ip_xpath = f'//tr[@id="name-{index}"]//td/span[@class="vmgraphics"]/text() | //tr[@id="name-{index}"]//td/text()'
        ip_texts = [t.strip() for t in tree.xpath(ip_xpath) if re.match(r'\d+\.\d+\.\d+\.\d+/\d+', t)]
        ip_list = [ip.split('/')[0] for ip in ip_texts]

        attributes = {
            'vcpus': vcpus,
            'memory_mb': mem_mb,
            'ip_addresses': ip_list
        }

        payload_power = {
            'name': f'VM {name} State',
            'device_class': 'running',
            'icon': 'mdi:monitor'
        }
        self.mqtt_publish(payload_power, 'binary_sensor', power, json_attributes=attributes, create_config=create_config)

        payload_vcpu = {
            'name': f'VM {name} vCPUs',
            'unit_of_measurement': '',
            'icon': 'mdi:chip',
            'state_class': 'measurement'
        }
        self.mqtt_publish(payload_vcpu, 'sensor', vcpus, create_config=create_config)

        payload_mem = {
            'name': f'VM {name} Memory',
            'unit_of_measurement': 'MB',
            'icon': 'mdi:memory',
            'state_class': 'measurement'
        }
        self.mqtt_publish(payload_mem, 'sensor', mem_mb, create_config=create_config)
