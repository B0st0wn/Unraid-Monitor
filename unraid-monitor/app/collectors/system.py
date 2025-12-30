"""
System information collector for Unraid
Collects system-level metrics like uptime
"""
import time
import psutil
from .base import EntityUpdate, QueryCollector
from typing import Any, Dict, List


class SystemCollector(QueryCollector):
    name = 'system'
    interval = 60  # Update every minute for uptime
    query = None  # No GraphQL query needed, using local system calls

    def __init__(self, gql_client, logger, scan_interval: int):
        self.gql = gql_client
        self.logger = logger
        self.interval = scan_interval

    async def fetch(self) -> Dict[str, Any]:
        """Fetch system data using psutil"""
        try:
            # Calculate uptime
            uptime_seconds = int(time.time() - psutil.boot_time())

            return {
                'uptime_seconds': uptime_seconds
            }
        except Exception as e:
            self.logger.error(f"System data collection failed: {e}")
            return {}

    async def parse(self, data: Dict[str, Any]) -> List[EntityUpdate]:
        """Parse system data and return entity updates"""
        updates = []

        uptime_seconds = data.get('uptime_seconds', 0)
        if not uptime_seconds:
            return updates

        # Format uptime as human-readable string
        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        pretty = f"{days}d {hours}h {minutes}m {seconds}s"

        attributes = {
            'formatted': pretty
        }

        # Create uptime sensor
        updates.append(EntityUpdate(
            sensor_type='sensor',
            payload={
                'name': 'System Uptime',
                'icon': 'mdi:clock-outline',
                'state_class': 'measurement',
                'unit_of_measurement': 's'
            },
            state=uptime_seconds,
            attributes=attributes,
            unique_id_suffix='system_uptime',
            retain=True
        ))

        self.logger.debug(f"System uptime: {pretty}")

        return updates


# Export collector for dynamic loading
COLLECTOR = SystemCollector
