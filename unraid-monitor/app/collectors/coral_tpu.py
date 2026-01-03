"""
Coral TPU Collector - Monitors Google Coral Edge TPU devices on Unraid.

Supports:
  - PCIe/M.2 Coral TPUs (apex devices with temperature monitoring)
  - USB Coral TPUs (presence detection only, no temperature available)

Requires a PHP script to be installed on the Unraid server that reads sysfs data.
See extras/coral_status.php for the server-side script.
"""

from typing import Any, Dict, List, Optional
from .base import EntityUpdate, QueryCollector


# Endpoint paths to try in order of preference
ENDPOINT_PATHS = [
    '/plugins/coral/coral_status.php',        # Future official plugin
    '/plugins/dynamix/coral_status.php',      # Manual install location
    '/state/coral_status.json',               # User Scripts output
]


class CoralTPUCollector(QueryCollector):
    """
    Polls Coral TPU status via a user-installed endpoint.

    Flow:
      - Try multiple endpoint paths to find the coral_status script.
      - Fetch JSON data containing PCIe and USB Coral TPU information.
      - Publish per-device sensors and summary entities.

    Requires legacy auth (Cookie). Uses LegacyHTTPContext for HTTP requests.
    """

    name = 'coral_tpu'
    requires_legacy_auth = True
    query = None  # not GraphQL-based

    def __init__(self, gql_client, logger, interval: int, legacy_ctx: Optional[Any] = None):
        self.gql = gql_client
        self.logger = logger
        self.interval = int(interval)
        self.legacy_ctx = legacy_ctx
        self._endpoint: Optional[str] = None
        self._endpoint_checked = False

    async def fetch(self) -> Dict[str, Any]:
        """
        Returns Coral TPU data as a dict with 'pcie' and 'usb' device lists.
        """
        if not self.legacy_ctx:
            self.logger.debug('Coral TPU: legacy context missing (no username/password configured); skipping')
            return {}

        # Find working endpoint on first call
        if not self._endpoint_checked:
            await self._discover_endpoint()
            self._endpoint_checked = True

        if not self._endpoint:
            return {}

        try:
            self.logger.debug(f'Coral TPU: fetching from {self._endpoint}')
            r = await self.legacy_ctx.http_get(self._endpoint, timeout=30)

            if r.status_code == 404:
                self.logger.debug(f'Coral TPU: endpoint {self._endpoint} returned 404')
                return {}

            if r.status_code != 200:
                self.logger.warning(f'Coral TPU fetch failed: HTTP {r.status_code}')
                return {}

            raw_text = r.text
            self.logger.debug(f'Coral TPU: raw response ({len(raw_text)} chars): {raw_text[:500]}')

            try:
                data = r.json()
            except Exception as je:
                self.logger.warning(f'Coral TPU: failed to parse JSON response: {je}')
                return {}

            if not data:
                self.logger.debug('Coral TPU: empty response from endpoint')
                return {}

            pcie_count = len(data.get('pcie', []))
            usb_count = len(data.get('usb', []))
            self.logger.debug(f'Coral TPU: found {pcie_count} PCIe and {usb_count} USB device(s)')
            return data

        except Exception as e:
            self.logger.error(f'Coral TPU fetch error: {e}')
            return {}

    async def parse(self, data: Dict[str, Any]) -> List[EntityUpdate]:
        """
        Parse Coral TPU data and create sensor entities.

        For PCIe devices:
          - Temperature sensor (°C)
          - Status sensor (throttle state)
          - Presence binary sensor

        For USB devices:
          - Presence binary sensor
          - Initialized binary sensor

        Summary:
          - Total device count sensor
        """
        updates: List[EntityUpdate] = []

        if not isinstance(data, dict):
            return updates

        pcie_devices = data.get('pcie', [])
        usb_devices = data.get('usb', [])

        # Process PCIe Coral TPUs
        for device in pcie_devices:
            if not isinstance(device, dict):
                continue

            device_id = device.get('id', 'unknown')
            device_num = device_id.replace('apex_', '')
            device_path = device.get('device', f'/dev/apex{device_num}')

            # Temperature sensor (PCIe only)
            temp_c = device.get('temp_c')
            if temp_c is not None:
                try:
                    temp_val = float(temp_c)
                    updates.append(
                        EntityUpdate(
                            sensor_type='sensor',
                            payload={
                                'name': f'Coral TPU {device_num} Temperature',
                                'unit_of_measurement': '°C',
                                'icon': 'mdi:chip',
                                'state_class': 'measurement',
                                'device_class': 'temperature',
                            },
                            state=round(temp_val, 1),
                            attributes=self._build_pcie_attributes(device),
                            retain=False,
                            expire_after=max(self.interval * 2, 60),
                            unique_id_suffix=f'coral_pcie_{device_num}_temp',
                        )
                    )
                except (ValueError, TypeError) as e:
                    self.logger.debug(f'Coral TPU: invalid temperature value for {device_id}: {e}')

            # Throttle status sensor
            throttle_state = device.get('throttle_state', 'unknown')
            if throttle_state and throttle_state != 'unknown':
                # Map throttle states to human-readable labels
                state_labels = {
                    'normal': 'Normal',
                    'throttled_250': 'Throttled (250 MHz)',
                    'throttled_125': 'Throttled (125 MHz)',
                    'throttled_62': 'Throttled (62.5 MHz)',
                    'shutdown_risk': 'Critical - Shutdown Risk',
                }
                display_state = state_labels.get(throttle_state, throttle_state)

                updates.append(
                    EntityUpdate(
                        sensor_type='sensor',
                        payload={
                            'name': f'Coral TPU {device_num} Status',
                            'icon': self._get_status_icon(throttle_state),
                        },
                        state=display_state,
                        attributes={
                            'raw_state': throttle_state,
                            'temp_c': temp_c,
                            'device': device_path,
                        },
                        retain=False,
                        expire_after=max(self.interval * 2, 60),
                        unique_id_suffix=f'coral_pcie_{device_num}_status',
                    )
                )

            # Presence binary sensor
            updates.append(
                EntityUpdate(
                    sensor_type='binary_sensor',
                    payload={
                        'name': f'Coral TPU {device_num}',
                        'device_class': 'connectivity',
                        'icon': 'mdi:chip',
                    },
                    state='ON',
                    attributes={
                        'device': device_path,
                        'type': 'pcie',
                        'id': device_id,
                    },
                    retain=True,
                    unique_id_suffix=f'coral_pcie_{device_num}_presence',
                )
            )

        # Process USB Coral TPUs
        for idx, device in enumerate(usb_devices):
            if not isinstance(device, dict):
                continue

            device_id = device.get('id', f'usb_coral_{idx}')
            device_num = str(idx)
            bus = device.get('bus', 'unknown')
            usb_device = device.get('device', 'unknown')
            initialized = device.get('initialized', False)
            vendor_id = device.get('vendor_id', '')
            product_id = device.get('product_id', '')

            # Presence binary sensor
            updates.append(
                EntityUpdate(
                    sensor_type='binary_sensor',
                    payload={
                        'name': f'Coral USB {device_num}',
                        'device_class': 'connectivity',
                        'icon': 'mdi:usb',
                    },
                    state='ON',
                    attributes={
                        'bus': bus,
                        'usb_device': usb_device,
                        'type': 'usb',
                        'id': device_id,
                        'vendor_id': vendor_id,
                        'product_id': product_id,
                    },
                    retain=True,
                    unique_id_suffix=f'coral_usb_{device_num}_presence',
                )
            )

            # Initialized status binary sensor
            updates.append(
                EntityUpdate(
                    sensor_type='binary_sensor',
                    payload={
                        'name': f'Coral USB {device_num} Initialized',
                        'device_class': 'running',
                        'icon': 'mdi:check-circle' if initialized else 'mdi:alert-circle',
                    },
                    state='ON' if initialized else 'OFF',
                    attributes={
                        'vendor_id': vendor_id,
                        'product_id': product_id,
                        'description': 'Ready for inference' if initialized else 'Not yet accessed by application',
                    },
                    retain=False,
                    expire_after=max(self.interval * 2, 60),
                    unique_id_suffix=f'coral_usb_{device_num}_initialized',
                )
            )

        # Summary sensor
        total_count = len(pcie_devices) + len(usb_devices)
        if total_count > 0 or self._endpoint:  # Only create if we have devices or a working endpoint
            device_list = []
            for d in pcie_devices:
                device_list.append({'type': 'pcie', 'id': d.get('id', 'unknown')})
            for d in usb_devices:
                device_list.append({'type': 'usb', 'id': d.get('id', 'unknown')})

            updates.append(
                EntityUpdate(
                    sensor_type='sensor',
                    payload={
                        'name': 'Coral TPU Count',
                        'icon': 'mdi:counter',
                        'state_class': 'measurement',
                    },
                    state=total_count,
                    attributes={
                        'pcie_count': len(pcie_devices),
                        'usb_count': len(usb_devices),
                        'devices': device_list,
                    },
                    retain=False,
                    expire_after=max(self.interval * 2, 60),
                    unique_id_suffix='coral_tpu_count',
                )
            )

        return updates

    def _build_pcie_attributes(self, device: Dict[str, Any]) -> Dict[str, Any]:
        """Build attributes dict for PCIe device sensors."""
        attrs = {}

        device_path = device.get('device')
        if device_path:
            attrs['device'] = device_path

        # Trip points (throttle thresholds)
        trip_point_0 = device.get('trip_point0')
        if trip_point_0 is not None:
            try:
                attrs['trip_point_250mhz'] = round(int(trip_point_0) / 1000, 1)
            except (ValueError, TypeError):
                pass

        trip_point_1 = device.get('trip_point1')
        if trip_point_1 is not None:
            try:
                attrs['trip_point_125mhz'] = round(int(trip_point_1) / 1000, 1)
            except (ValueError, TypeError):
                pass

        trip_point_2 = device.get('trip_point2')
        if trip_point_2 is not None:
            try:
                attrs['trip_point_62mhz'] = round(int(trip_point_2) / 1000, 1)
            except (ValueError, TypeError):
                pass

        shutdown_temp = device.get('shutdown_temp')
        if shutdown_temp is not None:
            try:
                attrs['shutdown_temp'] = round(int(shutdown_temp) / 1000, 1)
            except (ValueError, TypeError):
                pass

        poll_interval = device.get('poll_interval')
        if poll_interval is not None:
            try:
                attrs['poll_interval_ms'] = int(poll_interval)
            except (ValueError, TypeError):
                pass

        throttle_state = device.get('throttle_state')
        if throttle_state:
            attrs['throttle_state'] = throttle_state

        return attrs

    def _get_status_icon(self, throttle_state: str) -> str:
        """Get appropriate icon based on throttle state."""
        icon_map = {
            'normal': 'mdi:speedometer',
            'throttled_250': 'mdi:speedometer-medium',
            'throttled_125': 'mdi:speedometer-slow',
            'throttled_62': 'mdi:alert',
            'shutdown_risk': 'mdi:alert-octagon',
        }
        return icon_map.get(throttle_state, 'mdi:help-circle')

    async def _discover_endpoint(self) -> None:
        """
        Try multiple endpoint paths to find a working coral_status script.
        """
        if not self.legacy_ctx:
            return

        for endpoint in ENDPOINT_PATHS:
            try:
                self.logger.debug(f'Coral TPU: checking endpoint {endpoint}')
                r = await self.legacy_ctx.http_get(endpoint, timeout=10)

                if r.status_code == 200:
                    # Verify it returns valid JSON
                    try:
                        data = r.json()
                        if isinstance(data, dict):
                            self._endpoint = endpoint
                            self.logger.info(f'Coral TPU: found working endpoint at {endpoint}')
                            return
                    except Exception:
                        self.logger.debug(f'Coral TPU: endpoint {endpoint} returned non-JSON response')
                        continue

            except Exception as e:
                self.logger.debug(f'Coral TPU: endpoint {endpoint} check failed: {e}')
                continue

        self.logger.info('Coral TPU: no working endpoint found. Install coral_status.php on Unraid server.')


COLLECTOR = CoralTPUCollector
