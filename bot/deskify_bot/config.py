"""Bot settings, read once from the environment.

The bot holds no secrets of its own in local mode. It talks to the Playground
unauthenticated and signs into the API through /auth/dev-sign-in, which only
exists on an API running with DESKIFY_ENVIRONMENT=dev. Point it at anything
else and sign-in fails with a 404 rather than quietly doing something worse.
"""

import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BotSettings:
    api_url: str = "http://localhost:8099"
    #: Who a Teams user signs in as when the map below does not name them.
    #: The Playground's mock user has no real directory entry, so in local
    #: mode every chat is somebody from the seed.
    default_email: str = "priya@northwind.example"
    #: {teams aad_object_id or id: deskify email}. Lets two Playground users
    #: (or two real test accounts) be two different Deskify people.
    user_map: dict[str, str] = field(default_factory=dict)
    #: Rows on the "pick a desk" card. A Teams card is not a floor plan; past
    #: a dozen buttons nobody reads them.
    max_desks_shown: int = 12


def load() -> BotSettings:
    raw_map = os.getenv("DESKIFY_BOT_USER_MAP", "").strip()
    return BotSettings(
        api_url=os.getenv("DESKIFY_API_URL", BotSettings.api_url).rstrip("/"),
        default_email=os.getenv("DESKIFY_BOT_DEFAULT_EMAIL", BotSettings.default_email),
        user_map=json.loads(raw_map) if raw_map else {},
    )
