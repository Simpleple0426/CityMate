"""HTTP routes grouped by business capability."""

from . import assistant, auth, commerce, community, shops, system

ROUTERS = (
    system.router,
    auth.router,
    shops.router,
    commerce.router,
    community.router,
    assistant.router,
)
