"""The conversation, button by button, against the fake API."""

from datetime import date

from deskify_bot import flow
from deskify_bot.deskify_client import ApiError

DAY = date(2026, 10, 2)


def dump(card) -> dict:
    return card.model_dump(by_alias=True, exclude_none=True)


def buttons(card) -> list[dict]:
    """Every Action.Execute on the card, wherever it sits."""
    found: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "Action.Execute":
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(dump(card))
    return found


def text(card) -> str:
    return str(dump(card))


async def run(data, client, settings, **kw):
    return await flow.handle(data, "tok", client, settings, **kw)


async def test_anything_unrecognised_is_the_menu(client, settings):
    card = await run({}, client, settings)
    assert "Hi Priya." in text(card)
    assert [b["data"]["action"] for b in buttons(card)] == ["book.start", "bookings.list"]


async def test_start_defaults_to_home_office(client, settings):
    card = await run({"action": "book.start"}, client, settings, today=DAY)
    office = next(e for e in dump(card)["body"] if e.get("id") == "site_id")
    assert office["value"] == "s-tampa"
    day = next(e for e in dump(card)["body"] if e.get("id") == "on")
    assert day["value"] == "2026-10-02"


async def test_floor_buttons_carry_the_whole_state(client, settings):
    card = await run({"action": "book.floors", "site_id": "s-tampa", "on": "2026-10-02"},
                     client, settings)
    pick = next(b for b in buttons(card) if b["data"]["action"] == "book.desks")
    assert pick["data"] == {"action": "book.desks", "site_id": "s-tampa", "floor_id": "f5",
                            "floor_name": "5F", "on": "2026-10-02"}


async def test_desks_are_free_desks_only_sorted_by_name(client, settings, api):
    api.taken.add("d1")
    card = await run({"action": "book.desks", "site_id": "s-tampa", "floor_id": "f5",
                      "floor_name": "5F", "on": "2026-10-02"}, client, settings)
    names = [b["title"] for b in buttons(card) if b["data"]["action"] == "book.confirm"]
    assert names == ["5F-N-02"]  # d1 is booked, r1 is a room


async def test_book_then_list_then_cancel(client, settings, api):
    card = await run({"action": "book.confirm", "resource_id": "d1", "desk_name": "5F-N-01",
                      "on": "2026-10-02"}, client, settings)
    assert "Booked" in text(card) and "5F-N-01" in text(card)

    card = await run({"action": "bookings.list"}, client, settings)
    assert "5F-N-01 · 5F · Tampa" in text(card)
    cancel = next(b for b in buttons(card) if b["data"]["action"] == "bookings.cancel")

    card = await run(cancel["data"], client, settings)
    assert "Cancelled." in text(card) and "Nothing booked." in text(card)
    assert api.bookings == []


async def test_refusal_is_explained_not_raised(client, settings, api):
    api.taken.add("d1")  # someone got there between the desk list and the tap
    card = await run({"action": "book.confirm", "resource_id": "d1", "desk_name": "5F-N-01",
                      "on": "2026-10-02"}, client, settings)
    assert "Couldn't book that" in text(card)
    assert "Someone booked that desk a moment ago." in text(card)


def test_policy_denials_use_their_params():
    e = ApiError(409, "POLICY_DENIED", denials=[
        {"code": "BOOKING_HORIZON_EXCEEDED", "params": {"limit_days": 14}}])
    assert e.explain() == "You can book up to 14 days ahead."


def test_unknown_code_falls_back_to_detail_then_generic():
    assert ApiError(400, "WHATEVER", detail="nope").explain() == "nope"
    assert ApiError(400, "WHATEVER").explain() == "That booking isn't allowed."
    # A known code with params missing does not crash the bot.
    assert ApiError(409, "CAPACITY_EXCEEDED", detail="full").explain() == "full"
