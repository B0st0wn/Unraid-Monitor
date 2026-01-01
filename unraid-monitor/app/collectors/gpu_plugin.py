import json
from lxml import etree
from app.utils import normalize_keys_lower
from typing import Any, Dict, List, Optional
from .base import EntityUpdate, QueryCollector


class GpuPluginCollector(QueryCollector):
    """
    Polls the Unraid GPU Stat plugin via legacy webGui endpoints.

    Flow:
      - Discover GPU map once by parsing /Dashboard for gpustat_statusm({...}).
      - Fetch live stats via /plugins/gpustat/gpustatusmulti.php?gpus=<json>.
      - Publish per-GPU sensors and a summary entity.

    Requires legacy auth (Cookie). Uses LegacyHTTPContext implicitly through the provided legacy_ctx.
    """

    name = 'gpu_plugin'
    requires_legacy_auth = True
    query = None  # not GraphQL-based

    def __init__(self, gql_client, logger, interval: int, legacy_ctx: Optional[Any] = None):
        self.gql = gql_client
        self.logger = logger
        self.interval = int(interval)
        self.legacy_ctx = legacy_ctx
        self.gpus: Optional[Dict[str, Any]] = None

    async def fetch(self) -> Dict[str, Any]:
        """
        Returns plugin JSON data as a dict keyed by gpu_id.
        """
        if not self.legacy_ctx:
            self.logger.warning('GPU plugin: legacy context missing (no username/password configured); skipping')
            return {}

        if self.gpus is None:
            await self._discover_gpus()
            if not self.gpus:
                return {}

        try:
            self.logger.debug(f'GPU plugin: fetching stats for GPUs: {json.dumps(self.gpus)}')
            r = await self.legacy_ctx.http_get(
                '/plugins/gpustat/gpustatusmulti.php',
                params={'gpus': json.dumps(self.gpus)},
                timeout=30,
            )
            if r.status_code != 200:
                self.logger.warning(f'GPU plugin fetch failed: HTTP {r.status_code}')
                return {}

            # Log raw response for debugging
            raw_text = r.text
            self.logger.debug(f'GPU plugin: raw response ({len(raw_text)} chars): {raw_text[:500]}')

            try:
                data = r.json()
            except Exception as je:
                self.logger.warning(f'GPU plugin: failed to parse JSON response: {je}')
                return {}

            if not data:
                self.logger.debug('GPU plugin: empty response from gpustatusmulti.php')
                return {}

            self.logger.debug(f'GPU plugin: received data for {len(data)} GPU(s): {list(data.keys())}')
            return data
        except Exception as e:
            self.logger.error(f'GPU plugin fetch error: {e}')
            return {}

    async def parse(self, data: Dict[str, Any]) -> List[EntityUpdate]:
        updates: List[EntityUpdate] = []
        if not isinstance(data, dict) or not data:
            return updates

        def is_valid(value: Any) -> bool:
            if value is None:
                return False
            str_val = str(value).strip()
            invalid = {'N/A', 'N\\/A', 'Unknown', 'unknown', ''}
            if str_val in invalid:
                return False
            try:
                cleaned = str_val
                for suffix in ['%', '°C', 'W', ' ']:
                    cleaned = cleaned.replace(suffix, '')
                float(cleaned.strip())
                return True
            except Exception:
                return False

        def get_field(d: dict, *keys: str) -> Any:
            """Get first matching field from multiple possible key names."""
            for key in keys:
                if key in d and d[key] is not None:
                    return d[key]
            return None

        for gpu_id, gpu_data in data.items():
            if not isinstance(gpu_data, dict):
                self.logger.debug(f'GPU plugin: skipping {gpu_id}, not a dict: {type(gpu_data)}')
                continue

            # Try multiple field names for GPU name/model
            name = get_field(gpu_data, 'name', 'model', 'productname') or f'GPU {gpu_id}'
            name = str(name)

            self.logger.debug(f'GPU plugin: parsing {gpu_id} ({name}): {list(gpu_data.keys())}')

            # Try multiple field names for utilization
            util = get_field(gpu_data, 'util', 'gpuutil', 'utilization', 'load')
            if is_valid(util):
                try:
                    load_pct = int(float(str(util).replace('%', '').strip()))
                except Exception:
                    load_pct = 0
                updates.append(
                    EntityUpdate(
                        sensor_type='sensor',
                        payload={
                            'name': f'{name} Load',
                            'unit_of_measurement': '%',
                            'icon': 'mdi:chart-line',
                            'state_class': 'measurement',
                        },
                        state=load_pct,
                        retain=False,
                        expire_after=max(self.interval * 2, 60),
                        unique_id_suffix=f'{gpu_id}_load',
                    )
                )

            if all(is_valid(gpu_data.get(k)) for k in ['memutil', 'memused', 'memtotal']):
                try:
                    mem_used = int(float(gpu_data['memused']))
                    mem_total = int(float(gpu_data['memtotal']))
                    mem_pct = int(float(str(gpu_data['memutil']).replace('%', '').strip()))
                    updates.append(
                        EntityUpdate(
                            sensor_type='sensor',
                            payload={
                                'name': f'{name} Memory Usage',
                                'unit_of_measurement': '%',
                                'icon': 'mdi:memory',
                                'state_class': 'measurement',
                            },
                            state=mem_pct,
                            attributes={'used': mem_used, 'total': mem_total},
                            retain=False,
                            expire_after=max(self.interval * 2, 60),
                            unique_id_suffix=f'{gpu_id}_mem',
                        )
                    )
                except Exception:
                    pass

            fan = gpu_data.get('fan')
            if is_valid(fan):
                try:
                    fan_pct = int(float(str(fan).replace('%', '').strip()))
                except Exception:
                    fan_pct = 0
                updates.append(
                    EntityUpdate(
                        sensor_type='sensor',
                        payload={
                            'name': f'{name} Fan Speed',
                            'unit_of_measurement': '%',
                            'icon': 'mdi:fan',
                            'state_class': 'measurement',
                        },
                        state=fan_pct,
                        retain=False,
                        expire_after=max(self.interval * 2, 60),
                        unique_id_suffix=f'{gpu_id}_fan',
                    )
                )

            power = gpu_data.get('power')
            if is_valid(power):
                try:
                    power_w = int(float(str(power).replace('W', '').strip()))
                except Exception:
                    power_w = 0
                updates.append(
                    EntityUpdate(
                        sensor_type='sensor',
                        payload={
                            'name': f'{name} Power Usage',
                            'unit_of_measurement': 'W',
                            'icon': 'mdi:flash',
                            'state_class': 'measurement',
                        },
                        state=power_w,
                        retain=False,
                        expire_after=max(self.interval * 2, 60),
                        unique_id_suffix=f'{gpu_id}_power',
                    )
                )

            temp = gpu_data.get('temp')
            if is_valid(temp):
                try:
                    temp_c = int(float(str(temp).replace('°C', '').strip()))
                except Exception:
                    temp_c = 0
                updates.append(
                    EntityUpdate(
                        sensor_type='sensor',
                        payload={
                            'name': f'{name} Temperature',
                            'unit_of_measurement': '°C',
                            'icon': 'mdi:thermometer',
                            'state_class': 'measurement',
                            'device_class': 'temperature',
                        },
                        state=temp_c,
                        retain=False,
                        expire_after=max(self.interval * 2, 60),
                        unique_id_suffix=f'{gpu_id}_temp',
                    )
                )

            if is_valid(util):
                try:
                    load_pct = int(float(str(util).replace('%', '').strip()))
                    valid_attrs = {k: v for k, v in gpu_data.items() if is_valid(v)}
                    valid_attrs = normalize_keys_lower(valid_attrs)
                    updates.append(
                        EntityUpdate(
                            sensor_type='sensor',
                            payload={
                                'name': name,
                                'icon': 'mdi:expansion-card',
                                'unit_of_measurement': '%',
                                'state_class': 'measurement',
                            },
                            state=load_pct,
                            attributes=valid_attrs,
                            retain=False,
                            expire_after=max(self.interval * 2, 60),
                            unique_id_suffix=f'{gpu_id}_summary',
                        )
                    )
                except Exception:
                    pass

        return updates

    def _extract_balanced_json(self, text: str, start_marker: str) -> Optional[str]:
        """
        Extract a balanced JSON object from text starting after the marker.
        Handles nested braces correctly.
        """
        idx = text.find(start_marker)
        if idx == -1:
            return None

        # Find the opening brace after the marker
        brace_start = text.find('{', idx + len(start_marker))
        if brace_start == -1:
            return None

        depth = 0
        in_string = False
        escape_next = False

        for i, char in enumerate(text[brace_start:], start=brace_start):
            if escape_next:
                escape_next = False
                continue

            if char == '\\' and in_string:
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    return text[brace_start:i + 1]

        return None

    async def _discover_gpus(self) -> None:
        """
        Fetch /Dashboard and parse gpustat_statusm(...) to discover GPUs.
        """
        if not self.legacy_ctx:
            return

        try:
            r = await self.legacy_ctx.http_get('/Dashboard', timeout=30)
            if r.status_code != 200:
                self.logger.warning(f'GPU discovery failed: HTTP {r.status_code}')
                return

            html_text = r.text
            self.logger.debug(f'GPU plugin: Dashboard response length: {len(html_text)} chars')

            # First try to find gpustat_statusm in the raw HTML (faster than xpath)
            if 'gpustat_statusm' not in html_text:
                self.logger.info('GPU plugin: gpustat_statusm not found on Dashboard (GPU Stats plugin may not be installed)')
                return

            # Try to extract directly from HTML text first
            gpus_json = self._extract_balanced_json(html_text, 'gpustat_statusm(')

            # If that fails, try parsing with lxml
            if not gpus_json:
                self.logger.debug('GPU plugin: trying xpath extraction')
                tree = etree.HTML(html_text)
                script_nodes = tree.xpath('.//script')

                for node in script_nodes:
                    script_text = node.text or ''
                    if 'gpustat_statusm' in script_text:
                        gpus_json = self._extract_balanced_json(script_text, 'gpustat_statusm(')
                        if gpus_json:
                            break

            if not gpus_json:
                self.logger.warning('GPU plugin discovery: found gpustat_statusm but unable to extract JSON')
                # Log a snippet around gpustat_statusm for debugging
                idx = html_text.find('gpustat_statusm')
                if idx != -1:
                    snippet = html_text[max(0, idx - 20):idx + 200]
                    self.logger.debug(f'GPU plugin: context around gpustat_statusm: {snippet}')
                return

            try:
                gpus_obj = json.loads(gpus_json)
            except json.JSONDecodeError as e:
                self.logger.warning(f'GPU plugin discovery: invalid JSON in gpustat_statusm: {e}')
                self.logger.debug(f'GPU plugin: JSON that failed to parse: {gpus_json[:500]}')
                return

            if isinstance(gpus_obj, dict) and gpus_obj:
                self.gpus = gpus_obj
                self.logger.info(f'GPU plugin: discovered {len(gpus_obj)} GPU(s): {list(gpus_obj.keys())}')
                # Log the structure of the first GPU for debugging
                first_key = next(iter(gpus_obj))
                self.logger.debug(f'GPU plugin: sample GPU config ({first_key}): {gpus_obj[first_key]}')
            else:
                self.logger.info('GPU plugin: gpustat_statusm returned empty or non-dict data')
        except Exception as e:
            self.logger.error(f'GPU discovery error: {e}')


COLLECTOR = GpuPluginCollector
