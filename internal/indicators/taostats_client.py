"""TaoStats API client — re-exports unified fetchers.taostats_client."""

from fetchers.taostats_client import (  # noqa: F401
    get_account,
    get_delegation_events,
    get_dtao_pool_latest,
    get_subnet_delegation_flow,
    get_subnet_identity,
    get_subnet_owner,
    get_subnet_registration_cost,
    get_tao_price,
    get_tao_price_history,
    get_transfers,
    is_available,
)

# Back-compat aliases
TAOSTATS_API_KEY = __import__("os").environ.get("TAOSTATS_API_KEY", "")
TAOSTATS_BASE_URL = "https://api.taostats.io/api/v1"
