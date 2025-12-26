"""
GraphQL disk data fetcher for Unraid 7.2+
Fetches disk usage information from Unraid's GraphQL API
"""
from .graphql_client import graphql_query


async def fetch_disk_data_graphql(server):
    """
    Fetch disk data from Unraid GraphQL API
    Returns INI-formatted string compatible with existing disk parser
    """
    query = """
        query {
          array {
            disks {
              name
              device
              size
              status
              temp
              fsType
              fsSize
              fsUsed
              fsFree
            }
            caches {
              name
              device
              size
              status
              temp
              fsType
              fsSize
              fsUsed
              fsFree
            }
          }
        }
    """

    data = await graphql_query(server, query, "disks")
    if not data:
        return None

    array_data = data.get('array', {})
    if not array_data:
        server.logger.warning("GraphQL: No array data in response")
        return None

    all_disks = []

    # Combine regular disks and cache disks
    if 'disks' in array_data and array_data['disks']:
        all_disks.extend(array_data['disks'])
    if 'caches' in array_data and array_data['caches']:
        all_disks.extend(array_data['caches'])

    if all_disks:
        server.logger.debug(f"GraphQL: Successfully fetched data for {len(all_disks)} disk(s)")
        return convert_graphql_to_ini(all_disks)
    else:
        server.logger.warning("GraphQL: No disk or cache data found")
        return None


def convert_graphql_to_ini(disks):
    """
    Convert GraphQL disk array to INI format expected by disk parser

    GraphQL returns sizes already in 1024-byte sectors (not 512-byte as initially thought)
    Parser expects values in 1024-byte sectors, so use values directly
    """
    ini_sections = []

    for i, disk in enumerate(disks):
        # Extract values with defaults
        name = disk.get('name', f'disk{i}')
        device = disk.get('device', '')
        temp = disk.get('temp', 0)
        status = disk.get('status', '')
        fs_type = disk.get('fsType', '')

        # Size values from GraphQL - testing shows they're already in 1024-byte sectors
        # Parser expects 1024-byte sectors, so use values directly
        sizesb = int(disk.get('size', 0) or 0)
        fssize = int(disk.get('fsSize', 0) or 0)
        fsused = int(disk.get('fsUsed', 0) or 0)
        fsfree = int(disk.get('fsFree', 0) or 0)

        # Build INI section
        section = f"[{name}]\n"
        section += f'name="{name}"\n'
        section += f'device="{device}"\n'
        section += f'temp="{temp}"\n'
        section += f'status="{status}"\n'
        section += f'fstype="{fs_type}"\n'
        section += f'sizesb="{sizesb}"\n'
        section += f'fssize="{fssize}"\n'
        section += f'fsused="{fsused}"\n'
        section += f'fsfree="{fsfree}"\n'

        ini_sections.append(section)

    return '\n'.join(ini_sections)
