"""
GraphQL Array status data fetcher for Unraid 7.2+
Fetches array status, parity, and disk information
"""
from .graphql_client import graphql_query


async def fetch_array_data_graphql(server):
    """
    Fetch array status and disk data from Unraid GraphQL API
    Returns comprehensive array information including parity
    """
    query = """
        query {
          array {
            state
            capacity {
              kilobytes {
                free
                used
                total
              }
              disks {
                free
                used
                total
              }
            }
            parities {
              id
              name
              device
              size
              status
              temp
            }
            disks {
              id
              name
              device
              size
              status
              temp
              fsType
              fsSize
              fsUsed
              fsFree
            }
            caches {
              id
              name
              device
              size
              status
              temp
              fsType
              fsSize
              fsUsed
              fsFree
            }
          }
        }
    """

    data = await graphql_query(server, query, "array_status")
    if not data:
        return None

    array_data = data.get('array', {})
    if not array_data:
        server.logger.warning("GraphQL: No array data in response")
        return None

    server.logger.debug("GraphQL: Successfully fetched array data")
    return array_data


async def array_status_graphql(server, create_config=True):
    """
    Parse array status from GraphQL and publish to MQTT
    Publishes array state, capacity, and parity status
    """
    array_data = await fetch_array_data_graphql(server)
    if not array_data:
        return

    # Array state
    state = array_data.get('state', 'UNKNOWN')
    payload_state = {
        'name': 'Array State',
        'icon': 'mdi:server'
    }
    server.mqtt_publish(payload_state, 'sensor', state, create_config=create_config)

    # Array capacity
    capacity = array_data.get('capacity', {})
    kilobytes = capacity.get('kilobytes', {})

    if kilobytes:
        # Convert to int/float (API may return strings)
        total_kb = float(kilobytes.get('total', 0) or 0)
        used_kb = float(kilobytes.get('used', 0) or 0)
        free_kb = float(kilobytes.get('free', 0) or 0)

        # Convert to TB for display
        total_tb = round(total_kb / (1024 ** 3), 2) if total_kb else 0
        used_tb = round(used_kb / (1024 ** 3), 2) if used_kb else 0
        free_tb = round(free_kb / (1024 ** 3), 2) if free_kb else 0

        # Calculate usage percentage
        usage_pct = round((used_kb / total_kb * 100), 2) if total_kb else 0

        attributes = {
            'total_tb': total_tb,
            'used_tb': used_tb,
            'free_tb': free_tb
        }

        payload_usage = {
            'name': 'Array Usage',
            'unit_of_measurement': '%',
            'icon': 'mdi:database',
            'state_class': 'measurement'
        }
        server.mqtt_publish(
            payload_usage,
            'sensor',
            usage_pct,
            json_attributes=attributes,
            create_config=create_config
        )

    # Parity disks
    parities = array_data.get('parities', [])
    for parity in parities:
        if not isinstance(parity, dict):
            continue

        name = parity.get('name', 'parity')
        status = parity.get('status', 'UNKNOWN')
        temp = parity.get('temp', 0)

        # Parity status
        payload_parity_status = {
            'name': f'Parity {name} Status',
            'icon': 'mdi:shield-check'
        }
        server.mqtt_publish(payload_parity_status, 'sensor', status, create_config=create_config)

        # Parity temperature
        if temp:
            payload_parity_temp = {
                'name': f'Parity {name} Temperature',
                'unit_of_measurement': '°C',
                'device_class': 'temperature',
                'state_class': 'measurement'
            }
            server.mqtt_publish(payload_parity_temp, 'sensor', temp, create_config=create_config)

    server.logger.debug(f"Array status: {state}, Usage: {usage_pct if kilobytes else 'N/A'}%")


async def fetch_parity_history_graphql(server):
    """
    Fetch parity check history from Unraid GraphQL API
    Note: Parity history schema is not well-documented, disabling for now
    """
    # The parityHistory schema varies significantly between Unraid versions
    # and is not reliably available. Commenting out to avoid errors.
    # Users can still see parity status from array_status_graphql
    return None


async def parity_history_graphql(server, create_config=True):
    """
    Parse parity history and publish latest check info to MQTT
    """
    history = await fetch_parity_history_graphql(server)
    if not history:
        return

    # Get most recent parity check
    if history:
        latest = history[0] if isinstance(history, list) else history

        status = latest.get('status', 'UNKNOWN')
        duration = latest.get('duration', 0)
        speed = latest.get('speed', 0)
        errors = latest.get('errors', 0)

        attributes = {
            'duration_seconds': duration,
            'speed_mb_s': speed,
            'errors': errors,
            'start_time': latest.get('startTime', ''),
            'end_time': latest.get('endTime', '')
        }

        payload_parity = {
            'name': 'Last Parity Check',
            'icon': 'mdi:shield-sync'
        }
        server.mqtt_publish(
            payload_parity,
            'sensor',
            status,
            json_attributes=attributes,
            create_config=create_config
        )

        server.logger.debug(f"Parity check: {status}, Errors: {errors}")
