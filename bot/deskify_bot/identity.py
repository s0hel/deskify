"""Who a Teams user is in Deskify.

LOCAL ONLY, for now. The bot signs in through /auth/dev-sign-in, which takes
nothing but an email, so the mapping from Teams user to email is the whole of
"authentication" here. That is fine against the Playground and a dev API, and
it is not something to point at real people.

The real path is Teams SSO: Teams hands the bot an Entra token for the user,
and the API exchanges it for a Deskify token through the same OIDC leg the
apps will use. That waits on IdP credentials (T6). When it lands, it replaces
`email_for` + `dev_sign_in` below; nothing else in the bot needs to change,
because everything downstream only ever asks this module for a token.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from deskify_bot.config import BotSettings
from deskify_bot.deskify_client import DeskifyClient

#: Re-sign a little early so a token never expires between the check and the call.
EXPIRY_MARGIN_S = 30


@dataclass
class _Cached:
    token: str
    expires_at: float


class Identity:
    def __init__(self, settings: BotSettings, client: DeskifyClient, clock=time.monotonic):
        self._settings = settings
        self._client = client
        self._clock = clock
        self._tokens: dict[str, _Cached] = {}

    def email_for(self, aad_object_id: str | None, teams_id: str | None) -> str:
        for key in (aad_object_id, teams_id):
            if key and key in self._settings.user_map:
                return self._settings.user_map[key]
        return self._settings.default_email

    async def token_for(self, aad_object_id: str | None, teams_id: str | None) -> str:
        email = self.email_for(aad_object_id, teams_id)
        cached = self._tokens.get(email)
        if cached and cached.expires_at > self._clock():
            return cached.token
        token, ttl = await self._client.dev_sign_in(email)
        self._tokens[email] = _Cached(token, self._clock() + ttl - EXPIRY_MARGIN_S)
        return token
