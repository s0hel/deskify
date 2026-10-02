"""Adaptive Cards for the booking flow, as plain JSON.

Every button is an Action.Execute whose `data` carries the whole of the state
the next step needs (date, office, floor). The bot keeps no conversation
state, so a restart mid-flow loses nothing, and the card a person is looking
at is always the truth about where they are.

Each step's card REPLACES the previous one in place (the invoke response), so
a booking reads as one card that changes rather than a scroll of stale ones
with live-looking buttons.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from microsoft_teams.cards import AdaptiveCard

Card = dict[str, Any]


def _card(body: list[Card], actions: list[Card] | None = None) -> AdaptiveCard:
    card: Card = {"type": "AdaptiveCard", "version": "1.5", "body": body}
    if actions:
        card["actions"] = actions
    return AdaptiveCard.model_validate(card)


def _text(text: str, **kw) -> Card:
    return {"type": "TextBlock", "text": text, "wrap": True, **kw}


def _button(title: str, action: str, style: str | None = None, **data) -> Card:
    b: Card = {"type": "Action.Execute", "title": title, "verb": action,
               "data": {"action": action, **data}}
    if style:
        b["style"] = style
    return b


def _menu_buttons() -> list[Card]:
    return [_button("Book a desk", "book.start", "positive"),
            _button("My bookings", "bookings.list")]


def _label(on: date) -> str:
    # "Tue 01 Jun" next June reads as this June; say the year when it isn't this one.
    return on.strftime("%a %d %b" if on.year == datetime.now(UTC).year else "%a %d %b %Y")


def menu(display_name: str | None = None) -> AdaptiveCard:
    hello = f"Hi {display_name.split()[0]}." if display_name else "Hi."
    return _card(
        [_text(hello, size="Medium", weight="Bolder"),
         _text("I can book you a desk or show the ones you already have.")],
        _menu_buttons(),
    )


def pick_day_and_office(sites: list[dict], home_site_id: str | None, today: date) -> AdaptiveCard:
    choices = [{"title": s["name"], "value": s["id"]} for s in sorted(sites, key=lambda s: s["name"])]
    return _card(
        [
            _text("Book a desk", size="Medium", weight="Bolder"),
            {"type": "Input.Date", "id": "on", "label": "Day", "value": today.isoformat(),
             "min": today.isoformat(), "isRequired": True, "errorMessage": "Pick a day"},
            {"type": "Input.ChoiceSet", "id": "site_id", "label": "Office", "style": "compact",
             "choices": choices, "value": home_site_id or (choices[0]["value"] if choices else None),
             "isRequired": True, "errorMessage": "Pick an office"},
        ],
        [_button("Next", "book.floors", "positive"), _button("Back", "menu")],
    )


def pick_floor(site: dict, on: date, floors: list[dict]) -> AdaptiveCard:
    with_space = [f for f in floors if f["free"] > 0]
    body = [_text(f"{site['name']} · {_label(on)}", size="Medium", weight="Bolder")]
    if not with_space:
        body.append(_text("Every floor is full that day."))
        return _card(body, [_button("Pick another day", "book.start"), _button("Back", "menu")])
    body.append(_text("Which floor?"))
    body.append({
        "type": "ActionSet",
        "actions": [
            _button(f"{f['name']} — {f['free']} free", "book.desks",
                    site_id=site["id"], floor_id=f["id"], floor_name=f["name"],
                    on=on.isoformat())
            for f in with_space
        ],
    })
    return _card(body, [_button("Back", "book.start")])


def pick_desk(
    site_id: str, floor: dict, on: date, desks: list[dict], image_url: str | None = None
) -> AdaptiveCard:
    """The floor as a picture, and every free desk in one dropdown.

    The picture is a map, not a picker: a card cannot tell where on an image
    someone tapped (see floorplan.py). Its labels drop the floor prefix, so
    "N-03" on the plan is "5F-N-03" in the list.
    """
    back = [_button("Other floors", "book.floors", site_id=site_id, on=on.isoformat()),
            _button("Back", "menu")]
    body = [_text(f"{floor['name']} · {_label(on)}", size="Medium", weight="Bolder")]
    if not desks:
        body.append(_text("Nothing free on this floor any more."))
        return _card(body, back)
    if image_url:
        body.append({
            "type": "Image", "url": image_url, "size": "Stretch",
            "altText": f"Plan of {floor['name']}; free desks are green and labelled.",
            # The whole floor at card width is an overview; tapping opens it
            # full size, where the desk labels are readable.
            "selectAction": {"type": "Action.OpenUrl", "url": image_url, "title": "Open plan"},
        })
        body.append(_text("🟢 free · 🔵 yours · ⚪ taken — tap the plan to enlarge",
                          size="Small", isSubtle=True, spacing="Small"))
    body.append({
        "type": "Input.ChoiceSet", "id": "resource_id", "label": f"{len(desks)} free desks",
        "style": "compact", "isRequired": True, "errorMessage": "Pick a desk",
        "choices": [{"title": d["name"], "value": d["id"]} for d in desks],
        "value": desks[0]["id"],
    })
    book = _button("Book", "book.confirm", "positive", on=on.isoformat(), floor_id=floor["id"])
    return _card(body, [book, *back])


def booked(desk_name: str, on: date) -> AdaptiveCard:
    return _card(
        [_text("Booked ✅", size="Medium", weight="Bolder", color="Good"),
         _text(f"**{desk_name}** on {_label(on)}.")],
        _menu_buttons(),
    )


def refused(reason: str) -> AdaptiveCard:
    return _card(
        [_text("Couldn't book that", size="Medium", weight="Bolder", color="Attention"),
         _text(reason)],
        _menu_buttons(),
    )


def my_bookings(bookings: list[dict], names: dict[str, str], notice: str | None = None) -> AdaptiveCard:
    body: list[Card] = [_text("My bookings", size="Medium", weight="Bolder")]
    if notice:
        body.append(_text(notice, color="Good"))
    upcoming = sorted(bookings, key=lambda b: b["local_date"])
    if not upcoming:
        body.append(_text("Nothing booked."))
    for b in upcoming:
        on = date.fromisoformat(b["local_date"])
        body.append({
            "type": "ColumnSet",
            "separator": True,
            "columns": [
                {"type": "Column", "width": "stretch", "verticalContentAlignment": "Center",
                 "items": [_text(f"**{_label(on)}** — {names.get(b['resource_id'], 'a desk')}")]},
                {"type": "Column", "width": "auto",
                 "items": [{"type": "ActionSet", "actions": [
                     _button("Cancel", "bookings.cancel", "destructive", booking_id=b["id"])]}]},
            ],
        })
    return _card(body, _menu_buttons())
