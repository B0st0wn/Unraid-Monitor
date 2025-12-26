"""
UPS data fetcher for Unraid (GraphQL mode)
Uses short-lived WebSocket connections to poll current UPS state
"""
import asyncio
import websockets
import unraid_parsers as parsers


async def ups_graphql(server, create_config=True):
    """
    Fetch current UPS data by opening a fresh WebSocket connection.
    The 'apcups' channel sends the last known state immediately on connect,
    which is updated by the dashboard every 10 seconds.
    """
    try:
        headers = {'Cookie': server.unraid_cookie}
        subprotocols = ['ws+meta.nchan']
        websocket_url = f'{server.unraid_ws}/sub/apcups'

        # Open connection, grab the cached current state, then close
        async with websockets.connect(websocket_url, subprotocols=subprotocols, extra_headers=headers, close_timeout=2) as ws:
            try:
                # nchan sends last message immediately on subscribe
                data = await asyncio.wait_for(ws.recv(), timeout=3)

                # Parse the WebSocket message
                parts = data.replace('\00', ' ').split('\n\n', 1)
                if len(parts) >= 2:
                    msg_data = parts[1].strip()
                    if msg_data and msg_data != '[]':
                        await parsers.apcups(server, msg_data, create_config=create_config)
                        server.logger.debug("UPS data fetched (current cached state)")
                    else:
                        server.logger.debug("Empty UPS data from WebSocket")
                else:
                    server.logger.debug("Invalid WebSocket UPS message format")
            except asyncio.TimeoutError:
                server.logger.debug("WebSocket UPS: No cached data available")

    except Exception as e:
        server.logger.debug(f"Failed to fetch UPS data via WebSocket: {e}")
