"""
GraphQL VM data collector for Unraid 7.2+
Fetches virtual machine information including running state
"""
import httpx
import re
from lxml import etree
from .base import EntityUpdate, QueryCollector
from typing import Any, Dict, List


class VMsCollector(QueryCollector):
    name = 'vms'
    interval = 30
    requires_legacy_auth = True  # Needs legacy_ctx for HTTP scraping
    query = """
        query {
          vms {
            id
            domains {
              id
              uuid
              name
              state
            }
          }
        }
    """

    def __init__(self, gql_client, logger, scan_interval: int, legacy_ctx):
        self.gql = gql_client
        self.logger = logger
        self.interval = scan_interval
        self.legacy_ctx = legacy_ctx

    async def fetch(self) -> Dict[str, Any]:
        """Fetch VM data from GraphQL"""
        try:
            return await self.gql.query(self.query)
        except Exception as e:
            self.logger.error(f"GraphQL VMs query failed: {e}")
            return {}

    async def _fetch_vm_specs(self) -> Dict[str, Dict[str, int]]:
        """
        Fetch VM specs (vCPU, memory) from HTTP endpoint
        GraphQL schema doesn't always include these fields
        """
        vm_specs = {}
        try:
            cookie, _ = await self.legacy_ctx.get_session()
            async with httpx.AsyncClient(verify=self.legacy_ctx.verify_ssl) as http:
                headers = {'Cookie': cookie}
                r = await http.get(f'{self.legacy_ctx.http_base_url}/VMMachines.php', headers=headers, timeout=30)
                tree = etree.HTML(r.text)
                vm_rows = tree.xpath('//tr[contains(@class, "sortable")]')

                for row in vm_rows:
                    vm_name = ''.join(row.xpath('.//span[@class="inner"]/a/text()')).strip()
                    if not vm_name:
                        continue

                    vcpu_text = ''.join(row.xpath(f'.//a[contains(@class, "vcpu-")]/text()')).strip()
                    try:
                        vcpus = int(vcpu_text)
                    except ValueError:
                        vcpus = 0

                    mem_text = ''.join(row.xpath('./td[4]/text()')).strip()
                    mem_mb = int(re.sub(r'[^\d]', '', mem_text)) if mem_text else 0

                    vm_specs[vm_name] = {'vcpus': vcpus, 'memory_mb': mem_mb}
        except Exception as e:
            self.logger.warning(f"Could not fetch VM specs from HTTP: {e}")

        return vm_specs

    async def parse(self, data: Dict[str, Any]) -> List[EntityUpdate]:
        """Parse VM data and return entity updates"""
        updates = []

        # Extract VMs from response
        vms_data = data.get('vms', {})
        if not vms_data:
            self.logger.debug("GraphQL: No VMs data in response")
            return updates

        # The response is: { vms: { id: ..., domains: [...] } }
        domains = vms_data.get('domains', [])
        if not isinstance(domains, list):
            domains = [domains] if domains else []

        if not domains:
            self.logger.debug("GraphQL: No VMs found")
            return updates

        self.logger.debug(f"GraphQL: Found {len(domains)} VM(s)")

        # Get detailed VM specs from HTTP
        vm_specs = await self._fetch_vm_specs()

        for vm in domains:
            name = vm.get('name', '')
            if not name:
                continue

            # Determine running state
            # GraphQL returns state like: 'running', 'shut off', 'paused', etc.
            state = vm.get('state', '').lower()
            is_running = 'running' in state
            power_state = 'ON' if is_running else 'OFF'

            uuid = vm.get('uuid', '')

            # Get vCPU and memory from HTTP fallback
            specs = vm_specs.get(name, {})
            vcpus = specs.get('vcpus', 0)
            memory_mb = specs.get('memory_mb', 0)

            # Build attributes
            attributes = {
                'uuid': uuid,
                'state': state
            }
            if vcpus:
                attributes['vcpus'] = vcpus
            if memory_mb:
                attributes['memory_mb'] = memory_mb

            # Create entity update for binary sensor (running state)
            updates.append(EntityUpdate(
                sensor_type='binary_sensor',
                payload={
                    'name': f'VM {name} State',
                    'device_class': 'running',
                    'icon': 'mdi:monitor'
                },
                state=power_state,
                attributes=attributes,
                unique_id_suffix=f'vm_{name}_state'
            ))

            # Create entity update for vCPU count sensor if available
            if vcpus:
                updates.append(EntityUpdate(
                    sensor_type='sensor',
                    payload={
                        'name': f'VM {name} vCPUs',
                        'unit_of_measurement': '',
                        'icon': 'mdi:chip',
                        'state_class': 'measurement'
                    },
                    state=vcpus,
                    unique_id_suffix=f'vm_{name}_vcpus'
                ))

            # Create entity update for memory sensor if available
            if memory_mb:
                updates.append(EntityUpdate(
                    sensor_type='sensor',
                    payload={
                        'name': f'VM {name} Memory',
                        'unit_of_measurement': 'MB',
                        'icon': 'mdi:memory',
                        'state_class': 'measurement'
                    },
                    state=memory_mb,
                    unique_id_suffix=f'vm_{name}_memory'
                ))

            self.logger.debug(f"VM '{name}': {power_state} ({state}){f', {vcpus} vCPU, {memory_mb} MB' if vcpus else ''}")

        return updates


# Export collector for dynamic loading
COLLECTOR = VMsCollector
