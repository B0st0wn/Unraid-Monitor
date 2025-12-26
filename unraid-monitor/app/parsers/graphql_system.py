"""
System metrics fetcher for Unraid (GraphQL mode)
Uses WebSocket for system metrics since GraphQL doesn't provide them

System metrics (RAM%, Flash%, Docker%, Fan speeds, Temperatures) are only
available via WebSocket 'update1' and 'temperature' channels.
"""
import asyncio
import websockets
import unraid_parsers as parsers


async def system_metrics_graphql(server, create_config=True):
    """
    Fetch system metrics via WebSocket (GraphQL doesn't provide these metrics)

    Connects to WebSocket channels:
    - 'update1': RAM%, Flash%, Log%, Docker%, Fan speeds
    - 'temperature': Temperature sensors (Mainboard, CPU, etc.)
    """
    try:
        headers = {'Cookie': server.unraid_cookie}
        subprotocols = ['ws+meta.nchan']

        # Subscribe to both update1 and temperature channels
        websocket_url = f'{server.unraid_ws}/sub/update1,temperature'

        try:
            async with websockets.connect(websocket_url, subprotocols=subprotocols, extra_headers=headers, close_timeout=5) as ws:
                # Wait for both messages with timeout
                timeout_time = asyncio.get_event_loop().time() + 15
                messages_received = 0

                while asyncio.get_event_loop().time() < timeout_time and messages_received < 2:
                    try:
                        data = await asyncio.wait_for(ws.recv(), timeout=5)

                        # Parse the WebSocket message
                        parts = data.replace('\00', ' ').split('\n\n', 1)
                        if len(parts) < 2:
                            continue

                        msg_data = parts[1].strip()
                        if not msg_data or msg_data == '[]':
                            continue

                        # Determine which channel this is from
                        # update1 contains JSON with memory/fan data
                        # temperature contains HTML with temperature data
                        if msg_data.startswith('{') or msg_data.startswith('['):
                            # JSON data - likely update1 (memory/fans)
                            await parsers.update1(server, msg_data, create_config=create_config)
                            server.logger.debug("System metrics (update1) fetched via WebSocket")
                            messages_received += 1
                        elif '<' in msg_data:
                            # HTML data - likely temperature
                            await parsers.temperature(server, msg_data, create_config=create_config)
                            server.logger.debug("Temperature sensors fetched via WebSocket")
                            messages_received += 1

                    except asyncio.TimeoutError:
                        break

                if messages_received == 0:
                    server.logger.debug("WebSocket system metrics: No data received")

        except Exception as e:
            server.logger.warning(f"WebSocket system metrics connection failed: {e}")

    except Exception:
        server.logger.exception("Failed to fetch system metrics")
