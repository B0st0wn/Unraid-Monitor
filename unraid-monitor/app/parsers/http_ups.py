"""
HTTP-based UPS polling for Unraid.
Polls UPS status pages to extract UPS data when WebSocket isn't sending updates.
"""
import httpx
import re
from typing import Optional, Dict


async def fetch_ups_http(server, create_config: bool = False):
    """
    Fetch UPS data by polling Unraid's UPS status pages.
    This works even when WebSocket isn't sending updates.
    """
    try:
        async with httpx.AsyncClient(verify=False) as client:
            headers = {'Cookie': server.unraid_cookie}

            # Try multiple possible UPS endpoints
            endpoints = [
                '/plugins/dynamix.apcupsd/include/UPSstatus.php',
                '/Settings/UPSsettings',
                '/Dashboard',  # UPS widget might be on dashboard
            ]

            ups_data = None
            for endpoint in endpoints:
                try:
                    response = await client.get(
                        f'{server.unraid_url}{endpoint}',
                        headers=headers,
                        timeout=30.0,
                        follow_redirects=True
                    )

                    # Check if we got redirected to login
                    if '/login' in str(response.url):
                        continue

                    if response.status_code == 200:
                        ups_data = extract_ups_from_html(server, response.text)
                        if ups_data:
                            server.logger.debug(f"HTTP UPS: Found data from {endpoint}")
                            break

                except Exception:
                    continue

            if ups_data:
                # Use the existing UPS handler from parsers.ups
                from parsers.ups import handle_ups
                handle_ups(server, ups_data, create_config)
                server.logger.debug(f"HTTP UPS: Published {len(ups_data)} fields")
            else:
                server.logger.debug("HTTP UPS: No UPS data found in any endpoint")

    except httpx.RequestError as e:
        server.logger.error(f"HTTP UPS request failed: {e}")
    except Exception:
        server.logger.exception("Failed to fetch UPS data via HTTP")


def extract_ups_from_html(server, html: str) -> Optional[Dict[str, any]]:
    """
    Extract UPS data from HTML pages.
    Returns dict with UPS fields compatible with parsers.ups.handle_ups()
    """
    ups_data = {}

    # Pattern 1: Extract model name
    model_match = re.search(r'Model[:\s]+([A-Za-z0-9\s\-]+(?:UPS|XS|APC)[A-Za-z0-9\s\-]*)', html, re.IGNORECASE)
    if model_match:
        ups_data['MODEL'] = model_match.group(1).strip()

    # Pattern 2: Extract status (Online, On Battery, etc.)
    status_patterns = [
        r'Status[:\s]+<[^>]*class=["\']([^"\']*(?:green|red|yellow)[^"\']*)["\'][^>]*>([^<]+)',
        r'Status[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
    ]
    for pattern in status_patterns:
        status_match = re.search(pattern, html, re.IGNORECASE)
        if status_match:
            # Get the actual status text (last group)
            status_text = status_match.group(status_match.lastindex).strip()
            # Clean up HTML entities and tags
            status_text = re.sub(r'<[^>]+>', '', status_text)
            ups_data['STATUS'] = status_text
            break

    # Pattern 3: Extract battery percentage (validate range)
    battery_patterns = [
        r'Battery[^:]*:[^<]*?(\d+)\s*%',
        r'Charge[^:]*:[^<]*?(\d+)\s*%',
        r'BCHARGE[^:]*:[^<]*?(\d+)',
    ]
    for pattern in battery_patterns:
        battery_match = re.search(pattern, html, re.IGNORECASE)
        if battery_match:
            battery_val = int(battery_match.group(1))
            # Validate: battery should be 0-100%
            if 0 <= battery_val <= 100:
                ups_data['BCHARGE'] = battery_val
                server.logger.info(f"HTTP UPS: Battery={battery_val}%")
                break
            else:
                server.logger.debug(f"HTTP UPS: Rejected battery={battery_val}% (out of range)")

    # Pattern 4: Extract time left
    time_patterns = [
        r'Time\s+(?:Left|Remaining)[^:]*:[^<]*?(\d+)\s*(?:min|minutes)',
        r'TIMELEFT[^:]*:[^<]*?(\d+(?:\.\d+)?)',
    ]
    for pattern in time_patterns:
        time_match = re.search(pattern, html, re.IGNORECASE)
        if time_match:
            time_val = int(float(time_match.group(1)))
            # Validate: time left should be reasonable (0-999 minutes)
            if 0 <= time_val <= 999:
                ups_data['TIMELEFT'] = time_val
                server.logger.info(f"HTTP UPS: Time left={time_val} min")
                break

    # Pattern 5: Extract load percentage and watts (validate range)
    load_patterns = [
        r'Load[^:]*:[^<]*?(\d+)\s*W\s*\((\d+)\s*%\)',  # "180 W (20 %)"
        r'Load[^:]*:[^<]*?(\d+)\s*%',  # Just percentage
        r'LOADPCT[^:]*:[^<]*?(\d+)',
    ]
    for pattern in load_patterns:
        load_match = re.search(pattern, html, re.IGNORECASE)
        if load_match:
            if load_match.lastindex >= 2:
                # Has both watts and percentage
                watts = int(load_match.group(1))
                pct = int(load_match.group(2))
                # Validate: load should be 0-100%, watts should be reasonable
                if 0 <= pct <= 100 and 0 <= watts <= 10000:
                    ups_data['LOADW'] = watts
                    ups_data['LOADPCT'] = pct
                    server.logger.info(f"HTTP UPS: Load={pct}% ({watts}W)")
                    break
            else:
                # Just percentage
                pct = int(load_match.group(1))
                if 0 <= pct <= 100:
                    ups_data['LOADPCT'] = pct
                    server.logger.info(f"HTTP UPS: Load={pct}%")
                    break

    # Pattern 6: Extract nominal power
    power_match = re.search(r'Nominal\s+Power[^:]*:[^<]*?(\d+)\s*W', html, re.IGNORECASE)
    if power_match:
        power_val = int(power_match.group(1))
        if 0 < power_val <= 10000:  # Reasonable power range
            ups_data['NOMPOWER'] = power_val

    # Pattern 7: Extract voltages
    voltage_patterns = {
        'LINEV': r'Line\s+Voltage[^:]*:[^<]*?(\d+(?:\.\d+)?)\s*V',
        'OUTPUTV': r'Output\s+Voltage[^:]*:[^<]*?(\d+(?:\.\d+)?)\s*V',
        'BATTV': r'Battery\s+Voltage[^:]*:[^<]*?(\d+(?:\.\d+)?)\s*V',
    }
    for key, pattern in voltage_patterns.items():
        volt_match = re.search(pattern, html, re.IGNORECASE)
        if volt_match:
            volt_val = float(volt_match.group(1))
            # Validate: voltage should be reasonable (0-500V)
            if 0 < volt_val <= 500:
                ups_data[key] = volt_val

    # Only return data if we found at least some key fields
    if len(ups_data) >= 2:
        server.logger.info(f"HTTP UPS: Extracted {len(ups_data)} fields: {list(ups_data.keys())}")
        return ups_data

    server.logger.debug(f"HTTP UPS: Insufficient data found ({len(ups_data)} fields)")
    return None
