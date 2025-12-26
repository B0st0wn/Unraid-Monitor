"""
HTTP-based memory polling for Unraid.
Polls dashboard pages to extract RAM, Flash, Log, and Docker usage percentages.
"""
import httpx
import re
from typing import Optional, Dict


async def fetch_memory_http(server, create_config: bool = False):
    """
    Fetch memory usage data by polling Unraid's dashboard page.
    This works even when WebSocket isn't sending updates.
    """
    try:
        # Since the Dashboard HTML doesn't contain the data (loaded via WebSocket/JS),
        # we need to rely on the WebSocket data from update1 channel.
        # The HTTP polling approach won't work for memory data.
        # Just skip for now and rely on WebSocket with retain flag.
        server.logger.debug("HTTP memory: Skipping - data not available via HTTP, using WebSocket instead")
        return

        async with httpx.AsyncClient(verify=False) as client:
            headers = {'Cookie': server.unraid_cookie}

            # Try the main dashboard first
            response = await client.get(
                f'{server.unraid_url}/Dashboard',
                headers=headers,
                timeout=30.0,
                follow_redirects=True
            )

            # Check if we got redirected to login
            if '/login' in str(response.url):
                server.logger.warning('HTTP memory fetch: Session expired, need to refresh cookie')
                return

            if response.status_code != 200:
                server.logger.error(f"HTTP memory fetch failed: HTTP {response.status_code}")
                return

            # Parse the HTML response
            content = response.text

            # DEBUG: Save HTML to file for inspection (first time only)
            if not hasattr(server, '_http_memory_debug_saved'):
                try:
                    with open('/tmp/dashboard_debug.html', 'w', encoding='utf-8') as f:
                        f.write(content)
                    server.logger.info("HTTP memory: Saved dashboard HTML to /tmp/dashboard_debug.html for debugging")
                    server._http_memory_debug_saved = True
                except Exception as e:
                    server.logger.debug(f"Could not save debug HTML: {e}")

            usage = extract_memory_from_html(server, content)

            if usage:
                # Publish sensors
                for name, percent in usage.items():
                    payload = {
                        'name': f'{name} Usage',
                        'unit_of_measurement': '%',
                        'icon': 'mdi:memory',
                        'state_class': 'measurement'
                    }
                    server.mqtt_publish(payload, 'sensor', percent, create_config=create_config, retain=True)

                server.logger.debug(f"HTTP memory: Published {len(usage)} sensors")
            else:
                server.logger.warning("HTTP memory: No memory data found in dashboard")

    except httpx.RequestError as e:
        server.logger.error(f"HTTP memory request failed: {e}")
    except Exception:
        server.logger.exception("Failed to fetch memory data via HTTP")


def extract_memory_from_html(server, html: str) -> Dict[str, int]:
    """
    Extract memory usage percentages from dashboard HTML.
    Returns dict like: {'RAM': 45, 'Flash': 12, 'Log': 5, 'Docker': 18}
    """
    usage = {}

    # Strategy: Find all percentages with their labels, then take FIRST valid match for each type
    # This prevents matching both actual value and "100%" reference texts

    # Pattern 1: Direct label: percentage format (most specific)
    # Example: "RAM: 45%" or "Memory 45 %"
    pattern = r'\b(RAM|Memory|Flash|Boot|Log|Logs|Syslog|Docker|Containers)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%'
    matches = re.findall(pattern, html, re.IGNORECASE)

    for match in matches:
        label, value = match[0], match[1]
        normalized_label = normalize_memory_label(label)

        # Only take FIRST match for each sensor type
        if normalized_label and normalized_label not in usage:
            try:
                percent = int(float(value))
                # Sanity check: filter out obviously wrong values
                if 0 <= percent <= 100:
                    usage[normalized_label] = percent
                    server.logger.info(f"HTTP memory: {normalized_label}={percent}% (matched '{label}: {value}%')")
                else:
                    server.logger.debug(f"HTTP memory: Rejected {normalized_label}={percent}% (out of range)")
            except (ValueError, IndexError):
                continue

    # If we didn't find all 4 sensors, log what we got
    if len(usage) < 4:
        server.logger.warning(f"HTTP memory: Only found {len(usage)}/4 sensors: {list(usage.keys())}")

    return usage


def normalize_memory_label(label: str) -> Optional[str]:
    """Normalize memory type labels to standard names"""
    label = label.strip().lower()

    if label in ('ram', 'memory'):
        return 'RAM'
    if label in ('flash', 'boot'):
        return 'Flash'
    if label in ('log', 'logs', 'syslog'):
        return 'Log'
    if label in ('docker', 'containers'):
        return 'Docker'

    return None
