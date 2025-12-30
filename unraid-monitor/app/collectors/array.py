"""
GraphQL Array status data collector for Unraid 7.2+
Fetches array status, capacity, and parity information
"""
from .base import EntityUpdate, QueryCollector
from typing import Any, Dict, List


class ArrayCollector(QueryCollector):
    name = 'array'
    interval = 30
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

    def __init__(self, gql_client, logger, scan_interval: int):
        self.gql = gql_client
        self.logger = logger
        self.interval = scan_interval

    async def fetch(self) -> Dict[str, Any]:
        """Fetch array data from GraphQL"""
        try:
            return await self.gql.query(self.query)
        except Exception as e:
            self.logger.error(f"GraphQL Array query failed: {e}")
            return {}

    async def parse(self, data: Dict[str, Any]) -> List[EntityUpdate]:
        """Parse array data and return entity updates"""
        updates = []

        # Extract array data from response
        array_data = data.get('array', {})
        if not array_data:
            self.logger.debug("GraphQL: No array data in response")
            return updates

        self.logger.debug("GraphQL: Successfully fetched array data")

        # Array state sensor
        state = array_data.get('state', 'UNKNOWN')
        updates.append(EntityUpdate(
            sensor_type='sensor',
            payload={
                'name': 'Array State',
                'icon': 'mdi:server'
            },
            state=state,
            unique_id_suffix='array_state'
        ))

        # Array capacity and usage
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

            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': 'Array Usage',
                    'unit_of_measurement': '%',
                    'icon': 'mdi:database',
                    'state_class': 'measurement'
                },
                state=usage_pct,
                attributes=attributes,
                unique_id_suffix='array_usage'
            ))

            self.logger.debug(f"Array status: {state}, Usage: {usage_pct}%")

        # Parity disks
        parities = array_data.get('parities', [])
        for parity in parities:
            if not isinstance(parity, dict):
                continue

            name = parity.get('name', 'parity')
            status = parity.get('status', 'UNKNOWN')
            temp = parity.get('temp', 0)
            size = parity.get('size', 0)

            # Parity status sensor
            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': f'Parity {name} Status',
                    'icon': 'mdi:shield-check'
                },
                state=status,
                unique_id_suffix=f'parity_{name}_status'
            ))

            # Parity temperature sensor
            if temp and temp > 0:
                updates.append(EntityUpdate(
                    sensor_type='sensor',
                    payload={
                        'name': f'Parity {name} Temperature',
                        'unit_of_measurement': '°C',
                        'device_class': 'temperature',
                        'state_class': 'measurement'
                    },
                    state=temp,
                    unique_id_suffix=f'parity_{name}_temperature'
                ))

            # Parity size sensor (in TB)
            if size and size > 0:
                try:
                    # Convert sectors to TB (assuming 1024 bytes per sector like disks)
                    size_tb = round((int(size) * 1024) / 1_000_000_000_000, 2)
                    updates.append(EntityUpdate(
                        sensor_type='sensor',
                        payload={
                            'name': f'Parity {name} Size',
                            'unit_of_measurement': 'TB',
                            'icon': 'mdi:harddisk',
                            'state_class': 'measurement'
                        },
                        state=size_tb,
                        unique_id_suffix=f'parity_{name}_size',
                        retain=True
                    ))
                except (ValueError, TypeError) as e:
                    self.logger.debug(f"Error calculating parity size for {name}: {e}")

            self.logger.debug(f"Parity {name}: Status={status}, Temp={temp}°C")

        return updates


# Export collector for dynamic loading
COLLECTOR = ArrayCollector
