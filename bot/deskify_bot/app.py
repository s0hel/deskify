"""Deskify for Microsoft Teams: the bot process.

    uv run python -m deskify_bot.app      # listens on :3978/api/messages

Any message gets the menu card; everything after that is card buttons
(Action.Execute), each answered by replacing the card in place. See flow.py.

Locally this runs with no Microsoft credentials and with incoming requests
unauthenticated (DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS=true), which is
what the Agents Playground expects. Against real Teams, set CLIENT_ID,
CLIENT_SECRET and TENANT_ID and drop that flag; the SDK then validates every
request's JWT itself.
"""

from __future__ import annotations

import asyncio
import logging

from microsoft_teams.api import (
    AdaptiveCardActionCardResponse,
    AdaptiveCardInvokeActivity,
    ConversationUpdateActivity,
    MessageActivity,
)
from microsoft_teams.apps import ActivityContext, App

from deskify_bot import config, flow
from deskify_bot.deskify_client import ApiError, DeskifyClient
from deskify_bot.identity import Identity

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("deskify_bot")

settings = config.load()
client = DeskifyClient(settings.api_url)
identity = Identity(settings, client)
app = App()


async def _token(account) -> str:
    return await identity.token_for(account.aad_object_id, account.id)


@app.on_conversation_update
async def on_added(ctx: ActivityContext[ConversationUpdateActivity]) -> None:
    """Greet once when the app is installed, so the chat is never a blank page."""
    added = ctx.activity.members_added or []
    if any(m.id == ctx.activity.recipient.id for m in added):
        await _open(ctx)


#: Typed shortcuts, matching commandLists in appPackage/manifest.json. Anything
#: else gets the menu: this is a bot with buttons, not a language parser.
COMMANDS = {"book": "book.start", "bookings": "bookings.list"}


@app.on_message
async def on_message(ctx: ActivityContext[MessageActivity]) -> None:
    word = (ctx.activity.text or "").strip().lower()
    await _open(ctx, COMMANDS.get(word, "menu"))


async def _open(ctx: ActivityContext, action: str = "menu") -> None:
    try:
        token = await _token(ctx.activity.from_)
    except ApiError as e:
        log.warning("sign-in failed: %s %s", e.status, e.detail)
        await ctx.send(
            "I couldn't sign you in to Deskify. "
            "(Locally: is the API running with DESKIFY_ENVIRONMENT=dev, and seeded?)"
        )
        return
    await ctx.send(await flow.handle({"action": action}, token, client, settings))


@app.on_card_action_execute
async def on_card_action(ctx: ActivityContext[AdaptiveCardInvokeActivity]):
    data = dict(ctx.activity.value.action.data or {})
    token = await _token(ctx.activity.from_)
    card = await flow.handle(data, token, client, settings)
    return AdaptiveCardActionCardResponse(value=card)


if __name__ == "__main__":
    asyncio.run(app.start())
