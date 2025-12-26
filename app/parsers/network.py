from humanfriendly import parse_size

async def update3(self, msg_data, create_config):
    network_download = 0
    network_upload = 0

    for line in msg_data.splitlines():
        network = [n.strip() for n in line.split(' ')]
        if not network[0].startswith('eth'):
            continue

        network_download_text = ' '.join(network[1:3])
        network_download += round(parse_size(network_download_text) / 1000 / 1000, 1)
        payload_download = {
            'name': 'Download Throughput',
            'unit_of_measurement': 'Mbit/s',
            'icon': 'mdi:download',
            'state_class': 'measurement'
        }

        network_upload_text = ' '.join(network[3:5])
        network_upload += round(parse_size(network_upload_text) / 1000 / 1000, 1)
        payload_upload = {
            'name': 'Upload Throughput',
            'unit_of_measurement': 'Mbit/s',
            'icon': 'mdi:download',
            'state_class': 'measurement'
        }

        self.mqtt_publish(payload_download, 'sensor', network_download, create_config=create_config)
        self.mqtt_publish(payload_upload, 'sensor', network_upload, create_config=create_config)
