import os
import re
import sys
import time
import json
import httpx
import signal
import asyncio
import logging
import websockets
import unraid_parsers as parsers
from lxml import etree
from utils import load_file, normalize_str, handle_sigterm
from gmqtt import Client as MQTTClient, Message


class UnRAIDServer(object):
    def __init__(self, mqtt_config, unraid_config, loop: asyncio.AbstractEventLoop):
        unraid_host = unraid_config.get('host')
        unraid_port = unraid_config.get('port')
        unraid_ssl = unraid_config.get('ssl', False)
        unraid_address = f'{unraid_host}:{unraid_port}'
        unraid_protocol = 'https://' if unraid_ssl else 'http://'

        self.unraid_version = ''
        self.unraid_name = unraid_config.get('name')
        self.unraid_username = unraid_config.get('username')
        self.unraid_password = unraid_config.get('password')
        self.unraid_api_key = unraid_config.get('api_key')
        self.unraid_url = f'{unraid_protocol}{unraid_address}'
        self.unraid_ws = f'wss://{unraid_address}' if unraid_ssl else f'ws://{unraid_address}'
        self.scan_interval = unraid_config.get('scan_interval', 30)
        # Support environment variable overrides for faster real-time updates
        self.ups_scan_interval = int(os.getenv('UPS_SCAN_INTERVAL', unraid_config.get('ups_scan_interval', 30)))
        self.system_scan_interval = int(os.getenv('SYSTEM_SCAN_INTERVAL', unraid_config.get('system_scan_interval', 30)))
        self.share_parser_lastrun = 0
        self.share_parser_interval = 3600
        self.csrf_token = ''
        self.unraid_cookie = ''
        self.cookie_last_refresh = 0
        self.cookie_refresh_interval = 1800  # Refresh session every 30 minutes

        self.mqtt_connected = False
        self.mqtt_config = mqtt_config  # Store config for reconnection
        self.base_topic = mqtt_config.get('base_topic', 'unraid')
        self.reconnect_task = None
        self.vm_task = None
        self.unraid_task = None
        self.sensor_task = None
        self.watchdog_task = None
        self.ups_task = None
        self.graphql_disk_task = None
        self.graphql_docker_task = None
        self.graphql_vms_task = None
        self.graphql_array_task = None
        self.graphql_shares_task = None
        self.graphql_ups_task = None
        self.graphql_system_task = None
        self.http_memory_task = None
        self.http_ups_task = None
        self.watchdog_failures = 0
        self.last_ups_payload = None
        self.last_ups_time = 0

        unraid_id = normalize_str(self.unraid_name)
        will_message = Message(f'{self.base_topic}/{unraid_id}/connectivity/state', 'OFF', retain=True)
        # Use normalized ID for MQTT client (no spaces, MQTT spec compliant)
        mqtt_client_id = f'unraid_monitor_{unraid_id}'
        self.mqtt_client = MQTTClient(mqtt_client_id, will_message=will_message)
        asyncio.ensure_future(self.mqtt_connect(mqtt_config))

        self.logger = logging.getLogger(self.unraid_name)
        self.logger.setLevel(logging.INFO)
        unraid_logger = logging.StreamHandler(sys.stdout)
        unraid_logger_formatter = logging.Formatter(f'%(asctime)s [%(levelname)s] [{self.unraid_name}] %(message)s')
        unraid_logger.setFormatter(unraid_logger_formatter)
        self.logger.addHandler(unraid_logger)

        self.loop = loop

    def on_connect(self, client, flags, rc, properties):
        self.logger.info(f'MQTT on_connect callback: rc={rc}, flags={flags}, client_id={client._client_id}')
        self.mqtt_connected = True
        self.watchdog_failures = 0
        mover_payload = {'name': 'Mover'}
        self.mqtt_publish(mover_payload, 'button', state_value='OFF', create_config=True)
        self.mqtt_status(connected=True, create_config=True)

        # Start background tasks
        self.start_background_tasks()

    def on_message(self, client, topic, payload, qos, properties):
        pass

    def on_disconnect(self, client, packet, exc=None):
        self.logger.error(f'Disconnected from mqtt server - packet: {packet}, exc: {exc}')
        self.mqtt_connected = False

        # Cancel all background tasks before attempting reconnection
        self.cancel_background_tasks()

        # Wait a moment for tasks to finish cancelling before reconnecting
        asyncio.get_event_loop().call_later(2, lambda: self.schedule_mqtt_reconnect('disconnect callback'))

    def start_background_tasks(self):
        """Start all background tasks for data collection"""
        self.logger.info('Starting background tasks...')

        # Choose between WebSocket or GraphQL mode
        # Set USE_GRAPHQL=true in environment to use GraphQL instead of WebSocket
        use_graphql = os.getenv('USE_GRAPHQL', 'true').lower() == 'true'

        if use_graphql:
            self.logger.info('Using GraphQL mode for data collection')
            # GraphQL-based data collection
            self.graphql_disk_task = asyncio.ensure_future(self.graphql_disk_loop())
            self.graphql_docker_task = asyncio.ensure_future(self.graphql_docker_loop())
            self.graphql_vms_task = asyncio.ensure_future(self.graphql_vms_loop())
            self.graphql_array_task = asyncio.ensure_future(self.graphql_array_loop())
            self.graphql_shares_task = asyncio.ensure_future(self.graphql_shares_loop())
            self.graphql_ups_task = asyncio.ensure_future(self.graphql_ups_loop())
            self.graphql_system_task = asyncio.ensure_future(self.graphql_system_loop())
        else:
            self.logger.info('Using WebSocket mode for data collection')
            # Legacy WebSocket-based data collection
            self.unraid_task = asyncio.ensure_future(self.ws_connect())
            self.vm_task = asyncio.ensure_future(self.vm_sensor_loop())
            self.graphql_disk_task = asyncio.ensure_future(self.graphql_disk_loop())
            self.http_ups_task = asyncio.ensure_future(self.http_ups_loop())

        # System sensors always run (uses local psutil)
        self.sensor_task = asyncio.ensure_future(self.system_sensor_loop())
        self.watchdog_task = asyncio.ensure_future(self.mqtt_watchdog_loop())

    def cancel_background_tasks(self):
        """Cancel all background tasks"""
        self.logger.info('Cancelling background tasks...')
        tasks = [
            self.vm_task, self.unraid_task, self.sensor_task, self.watchdog_task,
            self.graphql_disk_task, self.graphql_docker_task, self.graphql_vms_task,
            self.graphql_array_task, self.graphql_shares_task, self.graphql_ups_task,
            self.graphql_system_task, self.http_ups_task
        ]
        for task in tasks:
            if task and not task.done():
                try:
                    task.cancel()
                except Exception as e:
                    self.logger.warning(f'Error cancelling task: {e}')

    async def mqtt_reconnect(self):
        """Reconnect to MQTT broker with exponential backoff"""
        retry_delay = 2
        max_retry_delay = 30  # Max 30 seconds between retries

        while not self.mqtt_connected:
            try:
                self.logger.info(f'Attempting MQTT reconnection in {retry_delay} seconds...')
                await asyncio.sleep(retry_delay)

                mqtt_host = self.mqtt_config.get('host')
                mqtt_port = self.mqtt_config.get('port', 1883)

                self.logger.info('Reconnecting to mqtt server...')
                await self.mqtt_client.connect(mqtt_host, mqtt_port)
                # on_connect callback will set mqtt_connected = True and restart tasks
                break

            except ConnectionRefusedError:
                self.logger.error('MQTT connection refused, retrying...')
                retry_delay = min(retry_delay * 2, max_retry_delay)
            except Exception as e:
                self.logger.exception(f'Exception during MQTT reconnection: {e}')
                retry_delay = min(retry_delay * 2, max_retry_delay)

    def mqtt_status(self, connected, create_config=False):
        status_payload = {
            'name': 'Connectivity',
            'device_class': 'connectivity'
        }
        state_value = 'ON' if connected else 'OFF'
        self.mqtt_publish(status_payload, 'binary_sensor', state_value, create_config=create_config, retain=True)

    def mqtt_publish(self, payload, sensor_type, state_value, json_attributes=None, create_config=False, retain=False):
        # Validate MQTT connection before publishing
        if not self.mqtt_connected:
            self.logger.warning(f'Skipping publish for {payload.get("name")} - MQTT not connected')
            return

        unraid_id = normalize_str(self.unraid_name)
        sensor_id = normalize_str(payload["name"])
        unraid_sensor_id = f'{unraid_id}_{sensor_id}'

        if create_config:
            device = {
                'name': self.unraid_name,
                'identifiers': f'unraid_{unraid_id}'.lower(),
                'model': 'Unraid',
                'manufacturer': 'Lime Technology'
            }
            if self.unraid_version:
                device['sw_version'] = self.unraid_version

            create_config = payload
            if state_value is not None:
                create_config['state_topic'] = f'{self.base_topic}/{unraid_id}/{sensor_id}/state'
            if json_attributes:
                create_config['json_attributes_topic'] = f'{self.base_topic}/{unraid_id}/{sensor_id}/attributes'
            if sensor_type == 'button':
                create_config['command_topic'] = f'{self.base_topic}/{unraid_id}/{sensor_id}/commands'

            if not sensor_id.startswith(('connectivity', 'array', 'share_', 'disk_', 'ups_')):
                expire_in_seconds = self.scan_interval * 4
                create_config['expire_after'] = expire_in_seconds if expire_in_seconds > 120 else 120

            config_fields = {
                'name': f'{payload["name"]}',
                'attribution': 'Data provided by UNRAID',
                'unique_id': unraid_sensor_id,
                'device': device
            }
            create_config.update(config_fields)

            try:
                config_topic = f'homeassistant/{sensor_type}/{unraid_sensor_id}/config'
                result = self.mqtt_client.publish(config_topic, json.dumps(create_config), retain=True)
                if result is not None and hasattr(result, 'rc') and result.rc != 0:
                    self.logger.error(f'MQTT config publish failed for {sensor_id}: rc={result.rc}, topic={config_topic}')
                    self.mqtt_connected = False
                    self.schedule_mqtt_reconnect('config publish failure')
                    return
            except Exception as e:
                self.logger.exception(f'MQTT publish exception during discovery config for {sensor_id}: {e}')
                self.mqtt_connected = False
                self.schedule_mqtt_reconnect('config publish exception')
                return

        if state_value is not None:
            topic = f'{self.base_topic}/{unraid_id}/{sensor_id}/state'
            try:
                if not self.mqtt_is_connected():
                    self.logger.warning(f'MQTT publish skipped (not connected): {topic}')
                    return
                result = self.mqtt_client.publish(topic, state_value, retain=retain)
                if result is not None and hasattr(result, 'rc') and result.rc != 0:
                    self.logger.warning(f'MQTT publish failed for {sensor_id}: rc={result.rc}, topic={topic}')
                else:
                    self.logger.debug(f'MQTT published: {topic} = {state_value}')
            except Exception:
                self.logger.exception(f'MQTT publish exception for state: {topic}')
                self.mqtt_connected = False
                self.schedule_mqtt_reconnect('publish failure')
                return

        if json_attributes:
            try:
                attr_topic = f'{self.base_topic}/{unraid_id}/{sensor_id}/attributes'
                result = self.mqtt_client.publish(attr_topic, json.dumps(json_attributes), retain=retain)
                if result is not None and hasattr(result, 'rc') and result.rc != 0:
                    self.logger.error(f'MQTT attributes publish failed for {sensor_id}: rc={result.rc}')
                    self.mqtt_connected = False
                    self.schedule_mqtt_reconnect('attributes publish failure')
                    return
            except Exception as e:
                self.logger.exception(f'MQTT publish exception for attributes {sensor_id}: {e}')
                self.mqtt_connected = False
                self.schedule_mqtt_reconnect('attributes publish exception')
                return

        if sensor_type == 'button':
            self.mqtt_client.subscribe(f'{self.base_topic}/{unraid_id}/{sensor_id}/commands', qos=0, retain=retain)

    def schedule_mqtt_reconnect(self, reason):
        if self.reconnect_task is None or self.reconnect_task.done():
            self.logger.info(f'Scheduling MQTT reconnection ({reason})...')
            self.reconnect_task = asyncio.ensure_future(self.mqtt_reconnect())

    def mqtt_is_connected(self):
        is_connected = getattr(self.mqtt_client, 'is_connected', None)
        if isinstance(is_connected, bool):
            actual_state = is_connected
        elif callable(is_connected):
            actual_state = is_connected()
        else:
            actual_state = self.mqtt_connected

        # Log state mismatch
        if actual_state != self.mqtt_connected:
            self.logger.warning(f'MQTT state mismatch: mqtt_connected={self.mqtt_connected}, actual={actual_state}')
            self.mqtt_connected = actual_state

        return actual_state

    async def mqtt_watchdog_loop(self):
        try:
            while self.mqtt_connected:
                await asyncio.sleep(30)
                if self.mqtt_is_connected():
                    self.watchdog_failures = 0
                    continue
                self.watchdog_failures += 1
                if self.watchdog_failures >= 3:
                    self.logger.warning('MQTT connection appears down; triggering reconnect')
                    self.watchdog_failures = 0
                    self.mqtt_connected = False
                    self.schedule_mqtt_reconnect('watchdog')
        except asyncio.CancelledError:
            self.logger.info('Watchdog loop cancelled')
            raise

    async def http_memory_loop(self):
        """Poll Unraid HTTP endpoints for memory usage data (RAM, Flash, Log, Docker)"""
        try:
            # Wait for session to establish
            await asyncio.sleep(10)

            while self.mqtt_connected:
                try:
                    # Refresh session cookie if needed
                    current_time = time.time()
                    if current_time - self.cookie_last_refresh > self.cookie_refresh_interval:
                        await self.refresh_unraid_session()

                    # Import parser
                    from parsers.http_memory import fetch_memory_http

                    # Fetch and publish memory data
                    await fetch_memory_http(self, create_config=True)

                except Exception:
                    self.logger.exception("Failed to fetch HTTP memory data")

                await asyncio.sleep(self.scan_interval)
        except asyncio.CancelledError:
            self.logger.info('HTTP memory loop cancelled')
            raise

    async def http_ups_loop(self):
        """Poll Unraid HTTP endpoints for UPS data"""
        try:
            # Wait for session to establish
            await asyncio.sleep(12)

            while self.mqtt_connected:
                try:
                    # Refresh session cookie if needed
                    current_time = time.time()
                    if current_time - self.cookie_last_refresh > self.cookie_refresh_interval:
                        await self.refresh_unraid_session()

                    # Import parser
                    from parsers.http_ups import fetch_ups_http

                    # Fetch and publish UPS data
                    await fetch_ups_http(self, create_config=True)

                except Exception:
                    self.logger.exception("Failed to fetch HTTP UPS data")

                await asyncio.sleep(self.scan_interval)
        except asyncio.CancelledError:
            self.logger.info('HTTP UPS loop cancelled')
            raise

    async def system_sensor_loop(self):
        try:
            while self.mqtt_connected:
                try:
                    await parsers.system_uptime(self, create_config=True)
                    await parsers.cpu_temperature_avg(self, create_config=True)
                    await parsers.cpu_utilization(self, create_config=True)
                except Exception:
                    self.logger.exception("Failed to publish system sensors.")
                await asyncio.sleep(self.scan_interval)
        except asyncio.CancelledError:
            self.logger.info('System sensor loop cancelled')
            raise

    async def refresh_unraid_session(self):
        """Refresh the Unraid session cookie"""
        try:
            payload = {
                'username': self.unraid_username,
                'password': self.unraid_password
            }
            async with httpx.AsyncClient() as http:
                r = await http.post(f'{self.unraid_url}/login', data=payload, timeout=15)
                self.unraid_cookie = r.headers.get('set-cookie')
                self.cookie_last_refresh = time.time()
                self.logger.info('Unraid session cookie refreshed')
                return True
        except Exception:
            self.logger.exception('Failed to refresh Unraid session')
            return False

    async def graphql_disk_loop(self):
        """Fetch disk usage data from GraphQL API (Unraid 7.2+)"""
        try:
            # Wait a bit before first run to let session establish
            await asyncio.sleep(5)

            while self.mqtt_connected:
                try:
                    # Refresh session cookie if needed (every 30 minutes)
                    current_time = time.time()
                    if current_time - self.cookie_last_refresh > self.cookie_refresh_interval:
                        await self.refresh_unraid_session()

                    # Import here to avoid circular imports
                    from parsers.graphql_disks import fetch_disk_data_graphql

                    # Fetch disk data from GraphQL
                    ini_data = await fetch_disk_data_graphql(self)

                    if ini_data:
                        # Parse using existing disk parser
                        await parsers.disks(self, ini_data, create_config=True)
                    else:
                        self.logger.debug("GraphQL disk data fetch returned no data")

                except Exception:
                    self.logger.exception("Failed to fetch GraphQL disk info")

                await asyncio.sleep(self.scan_interval)
        except asyncio.CancelledError:
            self.logger.info('GraphQL disk loop cancelled')
            raise

    async def graphql_docker_loop(self):
        """Fetch Docker container data from GraphQL API (Unraid 7.2+)"""
        try:
            await asyncio.sleep(5)

            while self.mqtt_connected:
                try:
                    current_time = time.time()
                    if current_time - self.cookie_last_refresh > self.cookie_refresh_interval:
                        await self.refresh_unraid_session()

                    from parsers.graphql_docker import docker_containers

                    await docker_containers(self, create_config=True)

                except Exception:
                    self.logger.exception("Failed to fetch GraphQL Docker info")

                await asyncio.sleep(self.scan_interval)
        except asyncio.CancelledError:
            self.logger.info('GraphQL Docker loop cancelled')
            raise

    async def graphql_vms_loop(self):
        """Fetch VM data from GraphQL API (Unraid 7.2+)"""
        try:
            await asyncio.sleep(5)

            while self.mqtt_connected:
                try:
                    current_time = time.time()
                    if current_time - self.cookie_last_refresh > self.cookie_refresh_interval:
                        await self.refresh_unraid_session()

                    from parsers.graphql_vms import vms_graphql

                    await vms_graphql(self, create_config=True)

                except Exception:
                    self.logger.exception("Failed to fetch GraphQL VM info")

                await asyncio.sleep(self.scan_interval)
        except asyncio.CancelledError:
            self.logger.info('GraphQL VMs loop cancelled')
            raise

    async def graphql_array_loop(self):
        """Fetch array status and parity data from GraphQL API (Unraid 7.2+)"""
        try:
            await asyncio.sleep(5)

            while self.mqtt_connected:
                try:
                    current_time = time.time()
                    if current_time - self.cookie_last_refresh > self.cookie_refresh_interval:
                        await self.refresh_unraid_session()

                    from parsers.graphql_array import array_status_graphql, parity_history_graphql

                    await array_status_graphql(self, create_config=True)
                    await parity_history_graphql(self, create_config=True)

                except Exception:
                    self.logger.exception("Failed to fetch GraphQL array info")

                await asyncio.sleep(self.scan_interval)
        except asyncio.CancelledError:
            self.logger.info('GraphQL array loop cancelled')
            raise

    async def graphql_shares_loop(self):
        """Fetch shares data from GraphQL API (Unraid 7.2+)"""
        try:
            await asyncio.sleep(5)

            while self.mqtt_connected:
                try:
                    current_time = time.time()
                    if current_time - self.cookie_last_refresh > self.cookie_refresh_interval:
                        await self.refresh_unraid_session()

                    from parsers.graphql_shares import shares_graphql

                    await shares_graphql(self, create_config=True)

                except Exception:
                    self.logger.exception("Failed to fetch GraphQL shares info")

                # Shares update less frequently (once per hour like the original)
                await asyncio.sleep(self.share_parser_interval)
        except asyncio.CancelledError:
            self.logger.info('GraphQL shares loop cancelled')
            raise

    async def graphql_ups_loop(self):
        """Fetch UPS data from GraphQL API (Unraid 7.2+)"""
        try:
            await asyncio.sleep(5)
            self.logger.info('GraphQL UPS loop started')

            while self.mqtt_connected:
                try:
                    current_time = time.time()
                    if current_time - self.cookie_last_refresh > self.cookie_refresh_interval:
                        await self.refresh_unraid_session()

                    from parsers.graphql_ups import ups_graphql

                    await ups_graphql(self, create_config=True)

                except Exception:
                    self.logger.exception("Failed to fetch GraphQL UPS info")

                await asyncio.sleep(self.ups_scan_interval)

            self.logger.warning(f'GraphQL UPS loop exited - mqtt_connected={self.mqtt_connected}')
        except asyncio.CancelledError:
            self.logger.info('GraphQL UPS loop cancelled')
            raise

    async def graphql_system_loop(self):
        """Fetch system metrics (RAM, Flash, Temps, Fans) via HTTP (Unraid 7.2+)"""
        try:
            await asyncio.sleep(5)
            self.logger.info('GraphQL system loop started')

            iteration = 0
            while self.mqtt_connected:
                try:
                    iteration += 1
                    self.logger.debug(f'System loop iteration {iteration}, mqtt_connected={self.mqtt_connected}')

                    current_time = time.time()
                    if current_time - self.cookie_last_refresh > self.cookie_refresh_interval:
                        await self.refresh_unraid_session()

                    from parsers.graphql_system import system_metrics_graphql

                    await system_metrics_graphql(self, create_config=True)

                except Exception:
                    self.logger.exception("Failed to fetch system metrics")

                await asyncio.sleep(self.system_scan_interval)

            self.logger.error(f'GraphQL system loop EXITED - mqtt_connected={self.mqtt_connected}, iteration={iteration}')
        except asyncio.CancelledError:
            self.logger.info('GraphQL system loop cancelled')
            raise

    async def vm_sensor_loop(self):
        try:
            while self.mqtt_connected:
                try:
                    # Refresh session cookie if needed (every 30 minutes)
                    current_time = time.time()
                    if current_time - self.cookie_last_refresh > self.cookie_refresh_interval:
                        await self.refresh_unraid_session()

                    async with httpx.AsyncClient() as http:
                        headers = {'Cookie': self.unraid_cookie}
                        r = await http.get(f'{self.unraid_url}/VMMachines.php', headers=headers, timeout=30)

                        # Check if we got redirected to login (session expired)
                        if '/login' in str(r.url):
                            self.logger.warning('Session expired, refreshing cookie...')
                            if await self.refresh_unraid_session():
                                # Retry the request with new cookie
                                headers = {'Cookie': self.unraid_cookie}
                                r = await http.get(f'{self.unraid_url}/VMMachines.php', headers=headers, timeout=30)

                        await parsers.vms(self, r.text, create_config=False)
                except Exception:
                    self.logger.exception("Failed to fetch VM info")
                await asyncio.sleep(self.scan_interval)
        except asyncio.CancelledError:
            self.logger.info('VM sensor loop cancelled')
            raise

    async def mqtt_connect(self, mqtt_config):
        mqtt_host = mqtt_config.get('host')
        mqtt_port = mqtt_config.get('port', 1883)
        mqtt_username = mqtt_config.get('username')
        mqtt_password = mqtt_config.get('password')

        self.mqtt_history = {}
        self.share_parser_lastrun = 0
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.set_auth_credentials(mqtt_username, mqtt_password)

        while True:
            try:
                self.logger.info(f'Connecting to MQTT broker {mqtt_host}:{mqtt_port} with client_id={self.mqtt_client._client_id}')
                await self.mqtt_client.connect(mqtt_host, mqtt_port)
                self.logger.info('MQTT connection successful')
                break
            except ConnectionRefusedError:
                self.logger.error(f'MQTT connection refused by {mqtt_host}:{mqtt_port}')
                await asyncio.sleep(30)
            except Exception:
                self.logger.exception(f'Exception connecting to MQTT broker {mqtt_host}:{mqtt_port}')
                await asyncio.sleep(30)

    async def ws_connect(self):
        try:
            while self.mqtt_connected:
                self.logger.info('Connecting to unraid...')
                last_msg = ''
                try:
                    payload = {
                        'username': self.unraid_username,
                        'password': self.unraid_password
                    }

                    async with httpx.AsyncClient() as http:
                        r = await http.post(f'{self.unraid_url}/login', data=payload, timeout=120)
                        self.unraid_cookie = r.headers.get('set-cookie')
                        r = await http.get(f'{self.unraid_url}/Dashboard', follow_redirects=True, timeout=120)
                        tree = etree.HTML(r.text)
                        version_elem = tree.xpath('.//div[@class="logo"]/text()[preceding-sibling::a]')
                        self.unraid_version = ''.join(c for c in ''.join(version_elem) if c.isdigit() or c == '.')

                    headers = {'Cookie': self.unraid_cookie}
                    subprotocols = ['ws+meta.nchan']

                    sub_channels = {
                        'update2': parsers.array_status,
                        'session': parsers.session,
                        'cpuload': parsers.cpuload,
                        'disks': parsers.disks,
                        'parity': parsers.parity,
                        'shares': parsers.shares,
                        'update1': parsers.update1,
                        'temperature': parsers.temperature,
                        'apcups': parsers.apcups
                    }

                    websocket_url = f'{self.unraid_ws}/sub/{",".join(sub_channels)}'
                    async with websockets.connect(websocket_url, subprotocols=subprotocols, extra_headers=headers) as websocket:
                        self.logger.info('Successfully connected to unraid')

                        while self.mqtt_connected:
                            try:
                                data = await asyncio.wait_for(websocket.recv(), timeout=15)
                                last_msg = data

                                # Parse message data with error handling
                                try:
                                    parts = data.replace('\00', ' ').split('\n\n', 1)
                                    if len(parts) < 2:
                                        self.logger.warning(f'Invalid message format: {data[:100]}')
                                        continue
                                    msg_data = parts[1].strip()

                                    msg_ids = re.findall(r'([-\[\d\],]+,[-\[\d\],]*)|$', data)[0].split(',')
                                    sub_channel = next((sub for (sub, msg) in zip(sub_channels, msg_ids) if msg.startswith('[')), None)

                                    if not sub_channel:
                                        self.logger.debug(f'Could not identify channel for message: {data[:100]}')
                                        continue

                                    msg_parser = sub_channels.get(sub_channel, parsers.default)

                                    if msg_data in ('', '[]'):
                                        continue

                                    if sub_channel == 'shares':
                                        current_time = time.time()
                                        time_passed = current_time - self.share_parser_lastrun
                                        if time_passed <= self.share_parser_interval:
                                            continue
                                        self.share_parser_lastrun = current_time

                                    if sub_channel not in self.mqtt_history:
                                        self.mqtt_history[sub_channel] = (time.time() - self.scan_interval)
                                        self.loop.create_task(msg_parser(self, msg_data, create_config=True))

                                    if self.scan_interval <= (time.time() - self.mqtt_history.get(sub_channel, time.time())):
                                        self.mqtt_history[sub_channel] = time.time()
                                        self.loop.create_task(msg_parser(self, msg_data, create_config=False))

                                except (ValueError, IndexError, StopIteration) as e:
                                    self.logger.warning(f'Error parsing websocket message: {e}')
                                    self.logger.debug(f'Problematic message: {data[:200]}')
                                    continue

                            except asyncio.TimeoutError:
                                self.logger.warning('WebSocket recv timeout, connection may be stale')
                                continue

                except (httpx.ConnectTimeout, httpx.ConnectError):
                    if self.mqtt_connected:
                        self.logger.error('Unraid WebSocket connection timeout, will retry...')
                        # Don't set connectivity to False - we have HTTP polling as backup
                    await asyncio.sleep(30)
                except Exception:
                    if self.mqtt_connected:
                        self.logger.exception('Unraid WebSocket connection failed, will retry...')
                        self.logger.error('Last message received:')
                        self.logger.error(last_msg)
                        # Don't set connectivity to False - we have HTTP polling as backup
                    await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.logger.info('WebSocket connection loop cancelled')
            raise


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, handle_sigterm)
    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict if name.startswith(('gmqtt'))]
    for log in loggers:
        logging.getLogger(log.name).disabled = True

    data_path = os.getenv('DATA_PATH', '/data')  # Add-on uses /data, standalone uses /data
    config = load_file(os.path.join(data_path, 'config.yaml'))

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    loop = asyncio.get_event_loop()

    for unraid_config in config.get('unraid'):
        UnRAIDServer(config.get('mqtt'), unraid_config, loop)

    loop.run_forever()
