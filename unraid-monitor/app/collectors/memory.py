"""
Memory information collector for Unraid
Collects detailed RAM usage including VM and Docker breakdown if available
"""
import psutil
from typing import Any, Dict, List, Optional
from .base import EntityUpdate, QueryCollector


class MemoryCollector(QueryCollector):
    """
    Collects memory statistics from Unraid via GraphQL with psutil fallback.

    Sensors created:
      - Memory Total (GiB)
      - Memory Used (GiB)
      - Memory Free (GiB)
      - Memory System (GiB) - if available from GraphQL
      - Memory VM (GiB) - if available from GraphQL
      - Memory Docker (GiB) - if available from GraphQL
    """

    name = 'memory'
    query = None  # We'll try multiple queries dynamically

    # GraphQL queries to try in order
    _queries = [
        # Try info query first
        """query { info { memory { total used free available cached buffers } } }""",
        # Try dashboard query
        """query { dashboard { memory { total free used system vm docker } } }""",
        # Try os query
        """query { os { memory { totalBytes usedBytes freeBytes availableBytes } } }""",
    ]

    def __init__(self, gql_client, logger, scan_interval: int):
        self.gql = gql_client
        self.logger = logger
        self.interval = scan_interval
        self._working_query: Optional[str] = None
        self._graphql_failed = False

    async def fetch(self) -> Dict[str, Any]:
        """Fetch memory data from GraphQL, falling back to psutil"""
        # Try GraphQL first (unless it's already failed)
        if not self._graphql_failed:
            data = await self._try_graphql_queries()
            if data:
                return data

        # Fallback to psutil
        return await self._fetch_from_psutil()

    async def _try_graphql_queries(self) -> Optional[Dict[str, Any]]:
        """Try GraphQL queries in order until one works"""
        queries = list(self._queries)

        # Use cached working query first if we have one
        if self._working_query:
            queries = [self._working_query] + [q for q in queries if q != self._working_query]

        for query in queries:
            try:
                result = await self.gql.query(query)
                if result:
                    memory_data = self._extract_memory_data(result)
                    if memory_data:
                        self._working_query = query
                        self.logger.debug(f'Memory: using GraphQL query')
                        return {'source': 'graphql', 'data': memory_data}
            except Exception as e:
                self.logger.debug(f'Memory GraphQL query failed: {e}')
                continue

        # Mark GraphQL as failed so we don't keep trying
        self._graphql_failed = True
        self.logger.info('Memory: GraphQL queries not available, using psutil fallback')
        return None

    def _extract_memory_data(self, result: Dict) -> Optional[Dict]:
        """Extract memory data from various possible response structures"""
        if not result:
            return None

        # Try info.memory
        if 'info' in result and result['info']:
            memory = result['info'].get('memory')
            if memory and isinstance(memory, dict):
                return memory

        # Try dashboard.memory
        if 'dashboard' in result and result['dashboard']:
            memory = result['dashboard'].get('memory')
            if memory and isinstance(memory, dict):
                return memory

        # Try os.memory
        if 'os' in result and result['os']:
            memory = result['os'].get('memory')
            if memory and isinstance(memory, dict):
                return memory

        return None

    async def _fetch_from_psutil(self) -> Dict[str, Any]:
        """Fallback: fetch memory info via psutil (reads /proc/meminfo)"""
        try:
            mem = psutil.virtual_memory()
            return {
                'source': 'psutil',
                'data': {
                    'total': mem.total,
                    'used': mem.used,
                    'free': mem.free,
                    'available': mem.available,
                    'cached': getattr(mem, 'cached', 0),
                    'buffers': getattr(mem, 'buffers', 0),
                    'percent': mem.percent
                }
            }
        except Exception as e:
            self.logger.error(f'Memory psutil fetch failed: {e}')
            return {}

    async def parse(self, data: Dict[str, Any]) -> List[EntityUpdate]:
        """Parse memory data and return entity updates"""
        updates: List[EntityUpdate] = []

        if not data:
            return updates

        source = data.get('source', 'unknown')
        mem_data = data.get('data', {})

        if not mem_data:
            return updates

        # Convert values to bytes (handles various input formats)
        total_bytes = self._to_bytes(mem_data.get('total') or mem_data.get('totalBytes', 0))
        used_bytes = self._to_bytes(mem_data.get('used') or mem_data.get('usedBytes', 0))
        free_bytes = self._to_bytes(mem_data.get('free') or mem_data.get('freeBytes', 0))
        available_bytes = self._to_bytes(mem_data.get('available') or mem_data.get('availableBytes', 0))

        # Optional breakdown (if GraphQL provides it)
        system_bytes = self._to_bytes(mem_data.get('system', 0))
        vm_bytes = self._to_bytes(mem_data.get('vm', 0))
        docker_bytes = self._to_bytes(mem_data.get('docker', 0))

        # Calculate free if not provided
        if free_bytes == 0 and total_bytes > 0 and used_bytes > 0:
            free_bytes = total_bytes - used_bytes

        # Convert to GiB
        total_gib = self._bytes_to_gib(total_bytes)
        used_gib = self._bytes_to_gib(used_bytes)
        free_gib = self._bytes_to_gib(free_bytes)

        # Memory Total sensor
        if total_gib > 0:
            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': 'Memory Total',
                    'unit_of_measurement': 'GiB',
                    'icon': 'mdi:memory',
                    'state_class': 'total',
                },
                state=total_gib,
                attributes={
                    'bytes': total_bytes,
                    'source': source
                },
                unique_id_suffix='memory_total',
                retain=True,
                expire_after=max(self.interval * 3, 120),
            ))

        # Memory Used sensor
        if total_gib > 0:  # Only show if we have total
            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': 'Memory Used',
                    'unit_of_measurement': 'GiB',
                    'icon': 'mdi:memory',
                    'state_class': 'measurement',
                },
                state=used_gib,
                attributes={
                    'bytes': used_bytes,
                    'percent': round((used_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0
                },
                unique_id_suffix='memory_used',
                retain=False,
                expire_after=max(self.interval * 3, 120),
            ))

        # Memory Free sensor
        if total_gib > 0:  # Only show if we have total
            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': 'Memory Free',
                    'unit_of_measurement': 'GiB',
                    'icon': 'mdi:memory',
                    'state_class': 'measurement',
                },
                state=free_gib,
                attributes={
                    'bytes': free_bytes,
                    'available_bytes': available_bytes,
                    'available_gib': self._bytes_to_gib(available_bytes)
                },
                unique_id_suffix='memory_free',
                retain=False,
                expire_after=max(self.interval * 3, 120),
            ))

        # Memory breakdown sensors (only if available from GraphQL)
        if system_bytes > 0:
            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': 'Memory System',
                    'unit_of_measurement': 'GiB',
                    'icon': 'mdi:cog',
                    'state_class': 'measurement',
                },
                state=self._bytes_to_gib(system_bytes),
                attributes={'bytes': system_bytes},
                unique_id_suffix='memory_system',
                retain=False,
                expire_after=max(self.interval * 3, 120),
            ))

        if vm_bytes > 0:
            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': 'Memory VM',
                    'unit_of_measurement': 'GiB',
                    'icon': 'mdi:monitor',
                    'state_class': 'measurement',
                },
                state=self._bytes_to_gib(vm_bytes),
                attributes={'bytes': vm_bytes},
                unique_id_suffix='memory_vm',
                retain=False,
                expire_after=max(self.interval * 3, 120),
            ))

        if docker_bytes > 0:
            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': 'Memory Docker',
                    'unit_of_measurement': 'GiB',
                    'icon': 'mdi:docker',
                    'state_class': 'measurement',
                },
                state=self._bytes_to_gib(docker_bytes),
                attributes={'bytes': docker_bytes},
                unique_id_suffix='memory_docker',
                retain=False,
                expire_after=max(self.interval * 3, 120),
            ))

        if updates:
            self.logger.debug(
                f'Memory ({source}): Total={total_gib} GiB, Used={used_gib} GiB, Free={free_gib} GiB'
            )

        return updates

    @staticmethod
    def _to_bytes(value: Any) -> int:
        """Convert value to bytes (handles various input formats)"""
        if value is None:
            return 0
        try:
            v = int(value)
            # If value is very small, it might be in KB, MB, or GB
            # Assume raw bytes if > 1000000 (1MB)
            return v
        except (ValueError, TypeError):
            try:
                return int(float(value))
            except Exception:
                return 0

    @staticmethod
    def _bytes_to_gib(bytes_val: int) -> float:
        """Convert bytes to GiB with 2 decimal precision"""
        if bytes_val <= 0:
            return 0.0
        return round(bytes_val / (1024 ** 3), 2)


# Export collector for dynamic loading
COLLECTOR = MemoryCollector
