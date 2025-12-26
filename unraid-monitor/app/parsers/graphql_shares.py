"""
GraphQL Shares data fetcher for Unraid 7.2+
Fetches user share information and usage
"""
from .graphql_client import graphql_query
from utils import normalize_str


async def fetch_shares_data_graphql(server):
    """
    Fetch shares data from Unraid GraphQL API
    Returns list of user shares with usage info
    """
    query = """
        query {
          shares {
            name
            comment
            allocator
            splitLevel
            include
            exclude
            cache
            floor
            size
            free
            used
          }
        }
    """

    data = await graphql_query(server, query, "shares")
    if not data:
        return None

    shares = data.get('shares', [])
    if not isinstance(shares, list):
        shares = [shares] if shares else []

    if not shares:
        server.logger.debug("GraphQL: No shares found")
        return []

    server.logger.debug(f"GraphQL: Found {len(shares)} share(s)")
    return shares


async def shares_graphql(server, create_config=True):
    """
    Parse shares data from GraphQL and publish to MQTT
    Creates sensors for each share with usage information
    """
    shares = await fetch_shares_data_graphql(server)
    if shares is None:
        return

    for share in shares:
        name = share.get('name', '')
        if not name:
            continue

        share_id = normalize_str(name)

        # Extract usage data - try both bytes and string formats
        size_bytes = float(share.get('size', 0) or 0)
        used_bytes = float(share.get('used', 0) or 0)
        free_bytes = float(share.get('free', 0) or 0)

        # If no size data, skip this share (don't publish 0%)
        if size_bytes == 0:
            server.logger.debug(f"Share '{name}': No size data available, skipping")
            continue

        # Convert to GB
        size_gb = round(size_bytes / (1024 ** 3), 2)
        used_gb = round(used_bytes / (1024 ** 3), 2)
        free_gb = round(free_bytes / (1024 ** 3), 2)

        # Calculate usage percentage
        usage_pct = round((used_bytes / size_bytes * 100), 2)

        # Build attributes
        attributes = {
            'comment': share.get('comment', ''),
            'allocator': share.get('allocator', ''),
            'cache': share.get('cache', ''),
            'size_gb': size_gb,
            'used_gb': used_gb,
            'free_gb': free_gb,
            'include': share.get('include', ''),
            'exclude': share.get('exclude', '')
        }

        # Publish usage percentage sensor
        payload_usage = {
            'name': f'Share {name} Usage',
            'unit_of_measurement': '%',
            'icon': 'mdi:folder-network',
            'state_class': 'measurement'
        }
        server.mqtt_publish(
            payload_usage,
            'sensor',
            usage_pct,
            json_attributes=attributes,
            create_config=create_config
        )

        server.logger.debug(f"Share '{name}': {usage_pct}% used ({used_gb}/{size_gb} GB)")
