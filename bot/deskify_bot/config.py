"""Bot settings, read once from the environment.

The bot holds no secrets of its own in local mode. It talks to the Playground
unauthenticated and signs into the API through /auth/dev-sign-in, which only
exists on an API running with DESKIFY_ENVIRONMENT=dev. Point it at anything
else and sign-in fails with a 404 rather than quietly doing something worse.
"""

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

#: The repo's own drawings, for running the bot from a checkout.
_REPO_PLANS = str(Path(__file__).resolve().parents[2] / "client" / "public" / "plans")


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
    #: Where the Teams CLIENT can reach this bot, for the floor-plan images.
    #: Locally that is the published port; in real Teams, the bot's public
    #: HTTPS origin (the same host as its messaging endpoint).
    public_url: str = "http://localhost:3978"
    #: A directory of <plan_asset_key>.svg, or the web app's origin.
    plans: str = _REPO_PLANS
    #: Signs image links. Random per process unless set, which only means a
    #: picture in a card from before a restart stops loading.
    image_secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))


def load() -> BotSettings:
    raw_map = os.getenv("DESKIFY_BOT_USER_MAP", "").strip()
    secret = os.getenv("DESKIFY_BOT_IMAGE_SECRET")
    return BotSettings(
        api_url=os.getenv("DESKIFY_API_URL", BotSettings.api_url).rstrip("/"),
        default_email=os.getenv("DESKIFY_BOT_DEFAULT_EMAIL", BotSettings.default_email),
        user_map=json.loads(raw_map) if raw_map else {},
        public_url=os.getenv("DESKIFY_BOT_PUBLIC_URL", BotSettings.public_url).rstrip("/"),
        plans=os.getenv("DESKIFY_PLANS", BotSettings.plans),
        **({"image_secret": secret.encode()} if secret else {}),
    )
