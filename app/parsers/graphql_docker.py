"""
GraphQL Docker container data fetcher for Unraid 7.2+
Fetches Docker container information including running state
"""
from .graphql_client import graphql_query
from utils import normalize_str


async def fetch_docker_data_graphql(server):
    """
    Fetch Docker container data from Unraid GraphQL API
    Publishes binary sensors for running state and additional metrics
    """
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

    data = await graphql_query(server, query, "docker_containers")
    if not data:
        return None

    # Extract containers from response
    containers = data.get('docker', {}).get('containers', [])
    if not containers:
        server.logger.warning("GraphQL: No Docker containers found")
        return None

    server.logger.debug(f"GraphQL: Found {len(containers)} Docker container(s)")
    return containers


async def docker_containers(server, create_config=True):
    """
    Parse Docker container data and publish to MQTT
    Creates binary sensors for running state
    """
    containers = await fetch_docker_data_graphql(server)
    if not containers:
        return

    for container in containers:
        # Extract container name (remove leading slash if present)
        names = container.get('names', [])
        if not names:
            continue

        # Container names come as array, typically ["/container_name"]
        name = names[0].lstrip('/') if isinstance(names, list) else str(names).lstrip('/')
        container_id = normalize_str(name)

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

        # Publish binary sensor for running state
        payload_state = {
            'name': f'Docker {name} State',
            'device_class': 'running',
            'icon': 'mdi:docker'
        }
        server.mqtt_publish(
            payload_state,
            'binary_sensor',
            power_state,
            json_attributes=attributes,
            create_config=create_config
        )

        server.logger.debug(f"Docker container '{name}': {power_state} ({state})")
