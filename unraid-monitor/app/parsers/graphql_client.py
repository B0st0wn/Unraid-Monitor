"""
Base GraphQL client for Unraid 7.2+ API
Provides shared functionality for all GraphQL queries
"""
import json
import httpx


async def graphql_query(server, query_string, operation_name=""):
    """
    Execute a GraphQL query against Unraid server

    Args:
        server: Server instance with connection details
        query_string: GraphQL query string
        operation_name: Optional operation name for logging

    Returns:
        dict: GraphQL response data, or None on error
    """
    graphql_request = {
        "query": query_string
    }

    try:
        # Build headers with authentication
        headers = {
            'Content-Type': 'application/json',
        }

        # Prefer API key (Unraid 7.2+), fall back to cookie
        if server.unraid_api_key:
            headers['x-api-key'] = server.unraid_api_key
        else:
            headers['Cookie'] = server.unraid_cookie

        async with httpx.AsyncClient(verify=False) as http:
            response = await http.post(
                f'{server.unraid_url}/graphql',
                json=graphql_request,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception as e:
                    server.logger.error(f"GraphQL ({operation_name}): Failed to parse JSON: {e}")
                    server.logger.debug(f"GraphQL ({operation_name}): Response: {response.text[:500]}")
                    return None

                # Validate response structure
                if not isinstance(data, dict):
                    server.logger.error(f"GraphQL ({operation_name}): Expected dict, got {type(data)}")
                    return None

                # Check for GraphQL errors
                if 'errors' in data:
                    server.logger.error(f"GraphQL ({operation_name}): Errors: {data['errors']}")
                    return None

                # Return the data payload
                if 'data' in data:
                    server.logger.debug(f"GraphQL ({operation_name}): Success")
                    return data['data']
                else:
                    server.logger.warning(f"GraphQL ({operation_name}): No data field in response")
                    server.logger.debug(f"GraphQL ({operation_name}): Response: {json.dumps(data, indent=2)}")
                    return None
            else:
                server.logger.error(f"GraphQL ({operation_name}): HTTP {response.status_code}: {response.text[:500]}")
                return None

    except httpx.ConnectError:
        server.logger.error(f"GraphQL ({operation_name}): Could not connect to /graphql endpoint")
        return None
    except Exception as e:
        server.logger.exception(f"GraphQL ({operation_name}): Exception: {e}")
        return None
