import math
import httpx
from lxml import etree
from utils import Preferences
from humanfriendly import parse_size

async def shares(self, msg_data, create_config):
    prefs = Preferences(msg_data)
    shares = prefs.as_dict()

    for n in shares:
        share = shares[n]
        share_name = share['name']
        share_disk_count = len(share['include'].split(','))
        share_floor_size = share['floor']
        share_nameorig = share['nameorig']
        share_use_cache = share['usecache']
        share_cachepool = share['cachepool']

        if share_use_cache in ['no', 'yes', 'prefer']:
            async with httpx.AsyncClient() as http:
                if self.unraid_version.startswith('6.11'):
                    headers = {'Cookie': self.unraid_cookie + ';ssz=ssz'}
                    params = {
                        'cmd': '/webGui/scripts/share_size',
                        'arg1': share_nameorig,
                        'arg2': 'ssz1',
                        'arg3': share_cachepool,
                        'csrf_token': self.csrf_token
                    }
                    await http.get(f'{self.unraid_url}/update.htm', params=params, headers=headers)
                    params = {
                        'compute': 'no',
                        'path': 'Shares',
                        'scale': 1,
                        'fill': 'ssz',
                        'number': '.'
                    }
                    r = await http.get(f'{self.unraid_url}/webGui/include/ShareList.php', params=params, headers=headers, timeout=600)
                else:
                    headers = {'Cookie': self.unraid_cookie}
                    data = {
                        'compute': share_nameorig,
                        'path': 'Shares',
                        'all': 1,
                        'csrf_token': self.csrf_token
                    }
                    r = await http.request("GET", url=f'{self.unraid_url}/webGui/include/ShareList.php', data=data, headers=headers, timeout=600)

                if r.status_code == httpx.codes.OK:
                    tree = etree.HTML(r.text)

                    size_total_used = tree.xpath(f'//td/a[text()="{share_nameorig}"]/ancestor::tr[1]/td[6]/text()')
                    size_total_used = next(iter(size_total_used or []), '0').strip()
                    size_total_used = parse_size(size_total_used)

                    size_total_free = tree.xpath(f'//td/a[text()="{share_nameorig}"]/ancestor::tr[1]/td[7]/text()')
                    size_total_free = next(iter(size_total_free or []), '0').strip()
                    size_total_free = parse_size(size_total_free)

                    size_cache_used = tree.xpath(f'//td/a[text()="{share_nameorig}"]/following::tr[1]/td[1][not(contains(text(), "Disk "))]/../td[6]/text()')
                    size_cache_used = next(iter(size_cache_used or []), '0').strip()
                    size_cache_used = parse_size(size_cache_used)

                    size_cache_free = tree.xpath(f'//td/a[text()="{share_nameorig}"]/following::tr[1]/td[1][not(contains(text(), "Disk "))]/../td[7]/text()')
                    size_cache_free = next(iter(size_cache_free or []), '0').strip()
                    size_cache_free = parse_size(size_cache_free)

                    share['used'] = int(size_total_used / 1000)
                    share['free'] = int((size_total_free - size_cache_free - size_cache_used) / 1000)

        if share['used'] == 0:
            continue

        if share.get('exclusive') == 'yes':
            share_disk_count = 1

        share_size_floor = share_disk_count * share_floor_size
        share['free'] -= share_size_floor
        share_size_total = share['used'] + share['free']
        share_used_pct = math.ceil((share['used'] / share_size_total) * 100)

        payload = {
            'name': f'Share {share_name.title()} Usage',
            'unit_of_measurement': '%',
            'icon': 'mdi:folder-network',
            'state_class': 'measurement'
        }

        self.mqtt_publish(payload, 'sensor', share_used_pct, json_attributes=share, create_config=create_config, retain=True)
