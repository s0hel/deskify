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
from datetime import date

from fastapi import FastAPI, Response
from microsoft_teams.api import (
    AdaptiveCardActionCardResponse,
    AdaptiveCardInvokeActivity,
    ConversationUpdateActivity,
    MessageActivity,
)
from microsoft_teams.apps import ActivityContext, App
from microsoft_teams.apps.http import FastAPIAdapter

from deskify_bot import config, flow
from deskify_bot.deskify_client import ApiError, DeskifyClient
from deskify_bot.floorplan import render_png
from deskify_bot.identity import Identity
from deskify_bot.plan_images import PlanSource, Signer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("deskify_bot")

settings = config.load()
client = DeskifyClient(settings.api_url)
identity = Identity(settings, client)
signer = Signer(settings.image_secret)
plans = PlanSource(settings.plans)

# Our own FastAPI app, handed to the SDK, so the floor pictures are served from
# the same port and host as /api/messages -- the one address that has to be
# reachable from Teams anyway.
web = FastAPI()
app = App(http_server_adapter=FastAPIAdapter(app=web))


@web.get("/floor/{floor_id}.png")
async def floor_png(floor_id: str, on: str, u: str, exp: str, sig: str) -> Response:
    """The floor picture for one user on one day. See plan_images.py for why it is signed."""
    if not signer.verify(floor_id, on, u, exp, sig):
        return Response(status_code=403)
    try:
        day = date.fromisoformat(on)
        token = await identity.token_for_email(u)
        floor = await client.floor(token, floor_id)
        states = await client.floor_states(token, floor_id, day)
    except (ValueError, ApiError):
        return Response(status_code=404)
    svg = await plans.svg(floor.get("plan_asset_key") or "")
    if svg is None:
        return Response(status_code=404)
    return Response(
        render_png(svg, floor, states), media_type="image/png",
        # Free/taken changes by the minute; a cached picture would be wrong.
        headers={"cache-control": "private, max-age=30"},
    )


def _plan_url_for(account):
    email = identity.email_for(account.aad_object_id, account.id)

    def plan_url(floor_id: str, on: date) -> str:
        return f"{settings.public_url}/floor/{floor_id}.png?{signer.query(floor_id, on, email)}"

    return plan_url


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
    card = await flow.handle(data, token, client, settings,
                             plan_url=_plan_url_for(ctx.activity.from_))
    return AdaptiveCardActionCardResponse(value=card)


if __name__ == "__main__":
    asyncio.run(app.start())
