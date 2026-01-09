"""
Memory information collector for Unraid
Collects detailed RAM usage including VM and Docker breakdown

Requires memory_status.php to be installed on the Unraid server.
See extras/memory_status.php for installation instructions.
"""
from typing import Any, Dict, List, Optional
from .base import EntityUpdate, QueryCollector


# Endpoint paths to try in order of preference
ENDPOINT_PATHS = [
    '/plugins/hass/memory_status.php',        # Recommended location
    '/plugins/unraid-monitor/memory_status.php',
    '/plugins/dynamix/memory_status.php',
    '/state/memory_status.json',
]


class MemoryCollector(QueryCollector):
    """
    Collects memory statistics from Unraid via a PHP endpoint.

    Sensors created:
      - Memory Total (GiB)
      - Memory Used (GiB)
      - Memory Free (GiB)
      - Memory System (GiB)
      - Memory VM (GiB)
      - Memory Docker (GiB)

    Requires legacy auth (Cookie) for HTTP access to the PHP endpoint.
    """

    name = 'memory'
    requires_legacy_auth = True
    query = None  # Not GraphQL-based

    def __init__(self, gql_client, logger, scan_interval: int, legacy_ctx: Optional[Any] = None):
        self.gql = gql_client
        self.logger = logger
        self.interval = scan_interval
        self.legacy_ctx = legacy_ctx
        self._endpoint: Optional[str] = None
        self._endpoint_checked = False

    async def fetch(self) -> Dict[str, Any]:
        """Fetch memory data from the PHP endpoint on Unraid"""
        if not self.legacy_ctx:
            self.logger.debug('Memory: legacy context missing (no username/password configured); skipping')
            return {}

        # Find working endpoint on first call
        if not self._endpoint_checked:
            await self._discover_endpoint()
            self._endpoint_checked = True

        if not self._endpoint:
            return {}

        try:
            self.logger.debug(f'Memory: fetching from {self._endpoint}')
            r = await self.legacy_ctx.http_get(self._endpoint, timeout=30)

            if r.status_code == 404:
                self.logger.debug(f'Memory: endpoint {self._endpoint} returned 404')
                return {}

            if r.status_code != 200:
                self.logger.warning(f'Memory fetch failed: HTTP {r.status_code}')
                return {}

            try:
                data = r.json()
            except Exception as je:
                self.logger.warning(f'Memory: failed to parse JSON response: {je}')
                return {}

            if not data or 'memory' not in data:
                self.logger.debug('Memory: empty or invalid response from endpoint')
                return {}

            return data.get('memory', {})

        except Exception as e:
            self.logger.error(f'Memory fetch error: {e}')
            return {}

    async def parse(self, data: Dict[str, Any]) -> List[EntityUpdate]:
        """Parse memory data and return entity updates"""
        updates: List[EntityUpdate] = []

        if not data:
            return updates

        # Extract values (PHP script provides both bytes and GiB)
        total_bytes = data.get('total', 0)
        used_bytes = data.get('used', 0)
        free_bytes = data.get('free', 0)
        available_bytes = data.get('available', 0)
        system_bytes = data.get('system', 0)
        vm_bytes = data.get('vm', 0)
        docker_bytes = data.get('docker', 0)
        percent_used = data.get('percent_used', 0)

        # Use pre-calculated GiB values from PHP if available, otherwise convert
        total_gib = data.get('total_gib') or self._bytes_to_gib(total_bytes)
        used_gib = data.get('used_gib') or self._bytes_to_gib(used_bytes)
        free_gib = data.get('free_gib') or self._bytes_to_gib(free_bytes)
        system_gib = data.get('system_gib') or self._bytes_to_gib(system_bytes)
        vm_gib = data.get('vm_gib') or self._bytes_to_gib(vm_bytes)
        docker_gib = data.get('docker_gib') or self._bytes_to_gib(docker_bytes)

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
                },
                unique_id_suffix='memory_total',
                retain=True,
                expire_after=max(self.interval * 3, 120),
            ))

        # Memory Used sensor
        if total_gib > 0:
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
                    'percent': percent_used
                },
                unique_id_suffix='memory_used',
                retain=False,
                expire_after=max(self.interval * 3, 120),
            ))

        # Memory Free sensor
        if total_gib > 0:
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
                    'available_gib': data.get('available_gib') or self._bytes_to_gib(available_bytes)
                },
                unique_id_suffix='memory_free',
                retain=False,
                expire_after=max(self.interval * 3, 120),
            ))

        # Memory System sensor
        if system_gib > 0:
            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': 'Memory System',
                    'unit_of_measurement': 'GiB',
                    'icon': 'mdi:cog',
                    'state_class': 'measurement',
                },
                state=system_gib,
                attributes={'bytes': system_bytes},
                unique_id_suffix='memory_system',
                retain=False,
                expire_after=max(self.interval * 3, 120),
            ))

        # Memory VM sensor
        if vm_gib > 0:
            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': 'Memory VM',
                    'unit_of_measurement': 'GiB',
                    'icon': 'mdi:monitor',
                    'state_class': 'measurement',
                },
                state=vm_gib,
                attributes={'bytes': vm_bytes},
                unique_id_suffix='memory_vm',
                retain=False,
                expire_after=max(self.interval * 3, 120),
            ))

        # Memory Docker sensor
        if docker_gib > 0:
            updates.append(EntityUpdate(
                sensor_type='sensor',
                payload={
                    'name': 'Memory Docker',
                    'unit_of_measurement': 'GiB',
                    'icon': 'mdi:docker',
                    'state_class': 'measurement',
                },
                state=docker_gib,
                attributes={'bytes': docker_bytes},
                unique_id_suffix='memory_docker',
                retain=False,
                expire_after=max(self.interval * 3, 120),
            ))

        if updates:
            self.logger.debug(
                f'Memory: Total={total_gib} GiB, Used={used_gib} GiB, Free={free_gib} GiB, '
                f'System={system_gib} GiB, VM={vm_gib} GiB, Docker={docker_gib} GiB'
            )

        return updates

    async def _discover_endpoint(self) -> None:
        """Try multiple endpoint paths to find a working memory_status script"""
        if not self.legacy_ctx:
            return

        for endpoint in ENDPOINT_PATHS:
            try:
                self.logger.debug(f'Memory: checking endpoint {endpoint}')
                r = await self.legacy_ctx.http_get(endpoint, timeout=10)

                if r.status_code == 200:
                    try:
                        data = r.json()
                        if isinstance(data, dict) and 'memory' in data:
                            self._endpoint = endpoint
                            self.logger.info(f'Memory: found working endpoint at {endpoint}')
                            return
                    except Exception:
                        self.logger.debug(f'Memory: endpoint {endpoint} returned non-JSON response')
                        continue

            except Exception as e:
                self.logger.debug(f'Memory: endpoint {endpoint} check failed: {e}')
                continue

        self.logger.info('Memory: no working endpoint found. Install memory_status.php on Unraid server.')

    @staticmethod
    def _bytes_to_gib(bytes_val: int) -> float:
        """Convert bytes to GiB with 2 decimal precision"""
        if not bytes_val or bytes_val <= 0:
            return 0.0
        return round(bytes_val / (1024 ** 3), 2)


# Export collector for dynamic loading
COLLECTOR = MemoryCollector
