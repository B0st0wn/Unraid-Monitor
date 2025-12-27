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

    Falls back to HTTP polling if WebSocket has no data.
    """
    update1_received = False
    temperature_received = False

    try:
        headers = {'Cookie': server.unraid_cookie}
        subprotocols = ['ws+meta.nchan']

        # Subscribe to both update1 and temperature channels
        websocket_url = f'{server.unraid_ws}/sub/update1,temperature'

        try:
            async with websockets.connect(
                websocket_url,
                subprotocols=subprotocols,
                extra_headers=headers,
                close_timeout=2,
                open_timeout=5,
                ping_interval=20,
                ping_timeout=10
            ) as ws:
                # Wait for both messages with reduced timeout
                timeout_time = asyncio.get_event_loop().time() + 5
                messages_received = 0

                while asyncio.get_event_loop().time() < timeout_time and messages_received < 2:
                    try:
                        data = await asyncio.wait_for(ws.recv(), timeout=3)

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
                            update1_received = True
                            messages_received += 1
                        elif '<' in msg_data:
                            # HTML data - likely temperature
                            server.logger.debug(f"WebSocket temperature data received ({len(msg_data)} chars)")
                            await parsers.temperature(server, msg_data, create_config=create_config)
                            server.logger.info("Temperature sensors fetched via WebSocket")
                            temperature_received = True
                            messages_received += 1

                    except asyncio.TimeoutError:
                        break

                if messages_received == 0:
                    server.logger.debug("WebSocket system metrics: No data received, trying HTTP fallback")

        except Exception as e:
            server.logger.debug(f"WebSocket system metrics connection failed: {e}, trying HTTP fallback")

    except Exception:
        server.logger.exception("Failed to fetch system metrics")

    # Fall back to HTTP scraping if WebSocket didn't get data
    if not temperature_received:
        try:
            await fetch_temperature_http(server, create_config=create_config)
        except Exception as e:
            server.logger.debug(f"HTTP temperature fallback failed: {e}")


async def fetch_temperature_http(server, create_config=True):
    """
    Fetch temperature data by scraping Dashboard HTML when WebSocket fails.
    """
    import httpx

    try:
        async with httpx.AsyncClient(verify=False) as client:
            headers = {'Cookie': server.unraid_cookie}
            server.logger.info("Attempting HTTP fallback for temperature data...")

            response = await client.get(
                f'{server.unraid_url}/Dashboard',
                headers=headers,
                timeout=10
            )

            if response.status_code == 504:
                server.logger.warning("Temperature HTTP: 504 Gateway Timeout - Unraid server is slow/overloaded")
                return

            if response.status_code == 200:
                # Extract temperature data from dashboard HTML
                await parsers.temperature(server, response.text, create_config=create_config)
                server.logger.info("Temperature sensors fetched successfully via HTTP fallback")
            else:
                server.logger.warning(f"Temperature HTTP: Unexpected status {response.status_code}")

    except httpx.TimeoutException as e:
        server.logger.warning(f"Temperature HTTP: Request timed out after 10s - {e}")
    except Exception as e:
        server.logger.warning(f"Temperature HTTP: Failed - {e}")
