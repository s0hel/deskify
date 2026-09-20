"""The layouts have to be true to their own drawing.

These are geometry invariants, not rendering taste. Each one here has already
caught something: desks placed outside the floorplate (the L-shaped Singapore
wing), a plate sized for more benching than was placed in it (Austin), and a
drawing regenerated without being committed.
"""

import math

import pytest

from app.floorplans import DESK_R, OFFICES, ROOM_R, FloorPlan, slugify
from app.plans import OUT_DIR, render

ALL = [office.floor for office in OFFICES]
IDS = [floor.key for floor in ALL]


def inside(x: float, y: float, floor: FloorPlan, pad: float = 0) -> bool:
    return any(
        r.x + pad <= x <= r.right - pad and r.y + pad <= y <= r.bottom - pad
        for r in floor.outline
    )


@pytest.mark.parametrize("floor", ALL, ids=IDS)
def test_every_desk_is_on_the_floorplate(floor: FloorPlan):
    """A plate made of more than one rect is easy to overflow -- the desk is
    then drawn on the page background, outside the building."""
    off = [d.name for d in floor.desks if not inside(d.x, d.y, floor, pad=DESK_R)]
    assert not off, f"{floor.key}: desks outside the plate: {off[:6]}"


@pytest.mark.parametrize("floor", ALL, ids=IDS)
def test_every_room_is_on_the_floorplate(floor: FloorPlan):
    off = [
        room.name
        for room in floor.rooms
        if not (
            inside(room.rect.x, room.rect.y, floor)
            and inside(room.rect.right, room.rect.bottom, floor)
        )
    ]
    assert not off, f"{floor.key}: rooms outside the plate: {off}"


@pytest.mark.parametrize("floor", ALL, ids=IDS)
def test_no_desk_is_in_a_void(floor: FloorPlan):
    """An atrium is a hole in the floor. Nobody sits in it."""
    for void in floor.voids:
        inside_void = [
            d.name
            for d in floor.desks
            if void.x <= d.x <= void.right and void.y <= d.y <= void.bottom
        ]
        assert not inside_void, f"{floor.key}: desks in the atrium: {inside_void[:6]}"


@pytest.mark.parametrize("floor", ALL, ids=IDS)
def test_desks_do_not_overlap_each_other(floor: FloorPlan):
    """FloorPlan.tsx draws each desk as a circle of DESK_R. Two closer than a
    diameter apart render as one blob you cannot tap separately."""
    points = [(d.x, d.y, d.name) for d in floor.desks]
    for i, (x1, y1, n1) in enumerate(points):
        for x2, y2, n2 in points[i + 1 :]:
            gap = math.hypot(x1 - x2, y1 - y2)
            assert gap >= DESK_R * 2, f"{floor.key}: {n1} and {n2} overlap ({gap:.0f}px)"


@pytest.mark.parametrize("floor", ALL, ids=IDS)
def test_bookable_rooms_do_not_swallow_a_desk(floor: FloorPlan):
    """A bookable room also gets a circle of ROOM_R at its centre."""
    for room in floor.rooms:
        if not room.bookable:
            continue
        for desk in floor.desks:
            gap = math.hypot(room.rect.cx - desk.x, room.rect.cy - desk.y)
            assert gap >= ROOM_R + DESK_R, f"{floor.key}: {room.name} sits on {desk.name}"


@pytest.mark.parametrize("floor", ALL, ids=IDS)
def test_desk_names_are_unique_within_a_floor(floor: FloorPlan):
    """resource is UNIQUE on (organization_id, site_id, name), so a collision
    here is a seed that half-fails rather than a layout that looks odd."""
    names = [d.name for d in floor.desks] + [r.name for r in floor.rooms if r.bookable]
    assert len(names) == len(set(names)), f"{floor.key}: duplicate resource names"


@pytest.mark.parametrize("floor", ALL, ids=IDS)
def test_every_desk_belongs_to_a_zone_the_floor_declares(floor: FloorPlan):
    declared = {z.name for z in floor.zones}
    used = {d.zone for d in floor.desks}
    assert used <= declared, f"{floor.key}: desks in undeclared zones {used - declared}"


@pytest.mark.parametrize("floor", ALL, ids=IDS)
def test_the_committed_drawing_matches_the_generator(floor: FloorPlan):
    """The SVGs are committed so a clean checkout builds without Python. That
    only holds if they are regenerated when the layout moves: `make plans`."""
    path = OUT_DIR / f"{floor.key}.svg"
    assert path.exists(), f"missing {path.name} -- run `make plans`"
    assert path.read_text() == render(floor), f"{path.name} is stale -- run `make plans`"


def test_the_plan_viewbox_is_the_plan_space_the_desks_are_in():
    """floor.plan_width/height go to the database and the <image> is drawn at
    exactly that box, so the SVG's own viewBox has to be the same numbers."""
    for floor in ALL:
        svg = (OUT_DIR / f"{floor.key}.svg").read_text()
        assert f'viewBox="0 0 {floor.width} {floor.height}"' in svg, floor.key


def test_slugify_matches_the_clients_rule():
    """Paired with `siteSlug` in client/src/booking/photos.ts, which resolves
    the office photograph. Same cases there."""
    assert slugify("Tampa") == "tampa"
    assert slugify("Berlin Mitte") == "berlin-mitte"
    assert slugify("Singapore Raffles") == "singapore-raffles"
    assert slugify("  Spaced  Out  ") == "spaced-out"
    assert slugify("St. John's Wood") == "st-john-s-wood"


def test_the_offices_are_distinct_and_named_for_their_files():
    keys = [office.floor.key for office in OFFICES]
    assert len(keys) == len(set(keys))
    for office in OFFICES:
        assert office.floor.key.startswith(office.slug), office.floor.key


def test_tampa_still_carries_the_performance_budget():
    """PRD §9.1 sets 300 desks as the floor-plan budget and TDD §9.3 makes the
    seeded floor the fixture. Shrinking it would quietly retire risk R8."""
    tampa = next(o for o in OFFICES if o.name == "Tampa")
    assert tampa.floor.desk_count == 300
