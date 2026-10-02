"""The booking conversation: one card action in, the next card out.

Kept apart from the Teams SDK so it can be tested against a real API with no
Teams in the loop -- the SDK's only job is to deliver `data` here and show
what comes back.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from microsoft_teams.cards import AdaptiveCard

from deskify_bot import cards
from deskify_bot.config import BotSettings
from deskify_bot.deskify_client import ApiError, DeskifyClient, free_desks

#: (floor_id, day) -> a URL the Teams client can load the floor picture from.
PlanUrl = Callable[[str, date], str]


async def handle(
    data: dict[str, Any], token: str, client: DeskifyClient, settings: BotSettings,
    today: date | None = None, plan_url: PlanUrl | None = None,
) -> AdaptiveCard:
    action = data.get("action")
    try:
        if action == "book.start":
            me = await client.me(token)
            sites = await client.sites(token)
            home = me["home_site"]
            # "Today" is the office's today, not the bot host's. The container
            # runs on UTC, so an evening in Tampa would otherwise open on tomorrow.
            tz = ZoneInfo(home["timezone"]) if home else UTC
            day = today or datetime.now(tz).date()
            return cards.pick_day_and_office(sites, home and home["id"], day)

        if action == "book.floors":
            on = date.fromisoformat(data["on"])
            site = next(s for s in await client.sites(token) if s["id"] == data["site_id"])
            floors = await client.floors(token, site["id"], on)
            return cards.pick_floor(site, on, floors)

        if action == "book.desks":
            on = date.fromisoformat(data["on"])
            floor = await client.floor(token, data["floor_id"])
            desks = free_desks(floor, await client.floor_states(token, floor["id"], on))
            image = plan_url(floor["id"], on) if plan_url and floor.get("plan_asset_key") else None
            return cards.pick_desk(data["site_id"], floor, on, desks, image)

        if action == "book.confirm":
            on = date.fromisoformat(data["on"])
            if not data.get("resource_id"):
                # The dropdown is required, but a client that skips input
                # validation would otherwise send a booking for "".
                return cards.refused("Pick a desk first.")
            await client.book(token, data["resource_id"], on)
            name = data.get("desk_name")
            if not name and data.get("floor_id"):
                floor = await client.floor(token, data["floor_id"])
                name = next((r["name"] for r in floor["resources"]
                             if r["id"] == data["resource_id"]), None)
            return cards.booked(name or "Your desk", on)

        if action == "bookings.list":
            return await _bookings(token, client)

        if action == "bookings.cancel":
            await client.cancel(token, data["booking_id"])
            return await _bookings(token, client, notice="Cancelled.")

        me = await client.me(token)
        return cards.menu(me.get("display_name"))
    except ApiError as e:
        return cards.refused(e.explain())


async def _bookings(token: str, client: DeskifyClient, notice: str | None = None) -> AdaptiveCard:
    bookings = await client.bookings(token)
    names = await client.resource_names(token) if bookings else {}
    return cards.my_bookings(bookings, names, notice)
