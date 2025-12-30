"""
GraphQL Docker container data collector for Unraid 7.2+
Fetches Docker container information including running state
"""
from .base import EntityUpdate, QueryCollector
from typing import Any, Dict, List


class DockerCollector(QueryCollector):
    name = 'docker'
    interval = 30
    query = """
        query {
          docker {
            containers {
              id
              names
              image
              state
              status
              autoStart
              ports {
                ip
                privatePort
                publicPort
                type
              }
            }
          }
        }
    """

    def __init__(self, gql_client, logger, scan_interval: int):
        self.gql = gql_client
        self.logger = logger
        self.interval = scan_interval

    async def fetch(self) -> Dict[str, Any]:
        """Fetch Docker data from GraphQL"""
        try:
            return await self.gql.query(self.query)
        except Exception as e:
            self.logger.error(f"GraphQL Docker query failed: {e}")
            return {}

    async def parse(self, data: Dict[str, Any]) -> List[EntityUpdate]:
        """Parse Docker data and return entity updates"""
        updates = []

        # Extract containers from response
        containers = data.get('docker', {}).get('containers', [])
        if not containers:
            self.logger.debug("GraphQL: No Docker containers found")
            return updates

        self.logger.debug(f"GraphQL: Found {len(containers)} Docker container(s)")

        for container in containers:
            # Extract container name (remove leading slash if present)
            names = container.get('names', [])
            if not names:
                continue

            # Container names come as array, typically ["/container_name"]
            name = names[0].lstrip('/') if isinstance(names, list) else str(names).lstrip('/')

            # Determine running state
            state = container.get('state', '').lower()
            is_running = state == 'running'
            power_state = 'ON' if is_running else 'OFF'

            # Extract additional info
            image = container.get('image', '')
            status = container.get('status', '')
            auto_start = container.get('autoStart', False)
            ports = container.get('ports', [])

            # Format port mappings for attributes
            port_mappings = []
            for port in ports:
                if isinstance(port, dict):
                    private = port.get('privatePort', '')
                    public = port.get('publicPort', '')
                    port_type = port.get('type', 'tcp')
                    if private and public:
                        port_mappings.append(f"{public}:{private}/{port_type}")

            # Build attributes
            attributes = {
                'container_id': container.get('id', '')[:12],  # Short ID
                'image': image,
                'status': status,
                'state': state,
                'auto_start': auto_start,
                'port_mappings': port_mappings
            }

            # Create entity update for binary sensor
            updates.append(EntityUpdate(
                sensor_type='binary_sensor',
                payload={
                    'name': f'Docker {name} State',
                    'device_class': 'running',
                    'icon': 'mdi:docker'
                },
                state=power_state,
                attributes=attributes,
                unique_id_suffix=f'docker_{name}_state'
            ))

            self.logger.debug(f"Docker container '{name}': {power_state} ({state})")

        return updates


# Export collector for dynamic loading
COLLECTOR = DockerCollector
