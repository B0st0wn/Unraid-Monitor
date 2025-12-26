"""
GraphQL VM data fetcher for Unraid 7.2+
Fetches virtual machine information including running state
"""
from .graphql_client import graphql_query
from utils import normalize_str


async def fetch_vm_data_graphql(server):
    """
    Fetch VM data from Unraid GraphQL API
    Returns list of VMs with state
    Note: Use minimal fields as schema varies by Unraid version
    """
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

    data = await graphql_query(server, query, "vms")
    if not data:
        return None

    # Extract VMs from response
    vms_data = data.get('vms', {})
    if not vms_data:
        server.logger.warning("GraphQL: No VMs data in response")
        return None

    # The response is: { vms: { id: ..., domains: [...] } }
    domains = vms_data.get('domains', [])
    if not isinstance(domains, list):
        domains = [domains] if domains else []

    if not domains:
        server.logger.debug("GraphQL: No VMs found")
        return []

    server.logger.debug(f"GraphQL: Found {len(domains)} VM(s)")
    return domains


async def vms_graphql(server, create_config=True):
    """
    Parse VM data from GraphQL and publish to MQTT
    Creates binary sensors for running state

    Note: GraphQL schema for VMs is limited in some Unraid versions,
    so we use HTTP fallback for detailed VM specs (vCPU, memory)
    """
    # Get basic VM state from GraphQL
    vms = await fetch_vm_data_graphql(server)
    if vms is None:
        # Fall back to HTTP parser if GraphQL fails
        server.logger.info("GraphQL VMs failed, using HTTP parser fallback")
        from . import vms as vms_http_parser
        import httpx
        try:
            async with httpx.AsyncClient(verify=False) as http:
                headers = {'Cookie': server.unraid_cookie}
                r = await http.get(f'{server.unraid_url}/VMMachines.php', headers=headers, timeout=30)
                await vms_http_parser.vms(server, r.text, create_config=create_config)
        except Exception:
            server.logger.exception("HTTP VM parser also failed")
        return

    # Get detailed VM info from HTTP as fallback for specs
    # (GraphQL schema doesn't always include vCPU/memory fields)
    vm_specs = {}
    try:
        import httpx
        from lxml import etree
        import re
        async with httpx.AsyncClient(verify=False) as http:
            headers = {'Cookie': server.unraid_cookie}
            r = await http.get(f'{server.unraid_url}/VMMachines.php', headers=headers, timeout=30)
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
    except Exception:
        server.logger.warning("Could not fetch VM specs from HTTP, will publish without vCPU/memory data")

    for vm in vms:
        name = vm.get('name', '')
        if not name:
            continue

        vm_id = normalize_str(name)

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

        # Publish binary sensor for running state
        payload_power = {
            'name': f'VM {name} State',
            'device_class': 'running',
            'icon': 'mdi:monitor'
        }
        server.mqtt_publish(
            payload_power,
            'binary_sensor',
            power_state,
            json_attributes=attributes,
            create_config=create_config
        )

        # Publish vCPU count sensor if available
        if vcpus:
            payload_vcpu = {
                'name': f'VM {name} vCPUs',
                'unit_of_measurement': '',
                'icon': 'mdi:chip',
                'state_class': 'measurement'
            }
            server.mqtt_publish(payload_vcpu, 'sensor', vcpus, create_config=create_config)

        # Publish memory sensor if available
        if memory_mb:
            payload_mem = {
                'name': f'VM {name} Memory',
                'unit_of_measurement': 'MB',
                'icon': 'mdi:memory',
                'state_class': 'measurement'
            }
            server.mqtt_publish(payload_mem, 'sensor', memory_mb, create_config=create_config)

        server.logger.debug(f"VM '{name}': {power_state} ({state}){f', {vcpus} vCPU, {memory_mb} MB' if vcpus else ''}")
