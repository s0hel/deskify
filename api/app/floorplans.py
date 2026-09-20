"""Floor layouts: ONE definition, two outputs.

A floor plan exists twice -- as desk coordinates in the database, and as a
drawing behind them -- and the two have to agree to the pixel, or the desks
sit in the corridor. So they are not authored twice. This module is the single
definition: `app.seed` reads the desks out of it and `app.plans` writes the
drawing, so a layout change moves both or neither. `tests/test_floorplans.py`
fails if the committed SVGs have drifted from it.

Coordinates are PLAN SPACE (TDD §9.1), frozen per floor. `floor.plan_width` /
`plan_height` ARE the SVG's viewBox, and every desk's plan_x/plan_y is a point
inside it; FloorPlan.tsx draws the image at exactly that box, so plan space and
drawing space are the same space by construction rather than by agreement.

The radii below must match the ones in FloorPlan.tsx. They are duplicated
rather than shared because the alternative is shipping a constant from Python
to TypeScript at build time, and the failure mode of drift here is a desk
overlapping its neighbour, which is visible immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Mirrors DESK_R / ROOM_R in client/src/floorplan/FloorPlan.tsx.
DESK_R = 16
ROOM_R = 26

#: Bench geometry. SEAT_DX is along a bench, ROW_DY across it (back to back).
#: SEAT_DX must clear 2*DESK_R plus enough room for a label at label zoom.
SEAT_DX = 64
ROW_DY = 76

BENCH_PAD_X = 34
BENCH_PAD_Y = 38


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass(frozen=True)
class Desk:
    name: str
    x: float
    y: float
    zone: str
    window: bool = False
    accessible: bool = False
    sit_stand: bool = False
    monitors: int = 2


@dataclass(frozen=True)
class Room:
    """A drawn room. `capacity` > 0 makes it a bookable resource too."""

    name: str
    rect: Rect
    capacity: int = 0
    #: meeting | focus | cafe | collab | core | wc. Only the fill changes.
    kind: str = "meeting"

    @property
    def bookable(self) -> bool:
        return self.capacity > 0


@dataclass(frozen=True)
class Zone:
    name: str
    rect: Rect


@dataclass
class FloorPlan:
    #: Also the plan_asset_key and the SVG filename: /plans/<key>.svg
    key: str
    site: str
    name: str
    ordinal: int
    width: int
    height: int
    #: The floorplate. More than one rect gives an L or a T.
    outline: list[Rect]
    zones: list[Zone] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    desks: list[Desk] = field(default_factory=list)
    #: Benches, drawn under the desks so they read as furniture.
    benches: list[Rect] = field(default_factory=list)
    #: A void the floorplate is cut out of -- an atrium, a lightwell.
    voids: list[Rect] = field(default_factory=list)

    @property
    def desk_count(self) -> int:
        return len(self.desks)


# ---------------------------------------------------------------------------
# The kit. Archetypes below compose these; nothing places a desk by hand.
# ---------------------------------------------------------------------------


def bench(
    x: float,
    y: float,
    seats: int,
    rows: int = 2,
) -> tuple[Rect, list[tuple[float, float]]]:
    """A run of back-to-back desks, and the rect they sit on.

    (x, y) is the FIRST desk's centre; everything else is derived, so the
    drawing cannot disagree with the seats.
    """
    points = [
        (x + seat * SEAT_DX, y + row * ROW_DY) for row in range(rows) for seat in range(seats)
    ]
    slab = Rect(
        x - BENCH_PAD_X,
        y - BENCH_PAD_Y,
        (seats - 1) * SEAT_DX + 2 * BENCH_PAD_X,
        (rows - 1) * ROW_DY + 2 * BENCH_PAD_Y,
    )
    return slab, points


def bench_w(seats: int) -> float:
    return (seats - 1) * SEAT_DX + 2 * BENCH_PAD_X


def bench_h(rows: int = 2) -> float:
    return (rows - 1) * ROW_DY + 2 * BENCH_PAD_Y


def meeting_strip(
    x: float, y: float, w: float, names: list[tuple[str, int, float]], gap: float = 14
) -> list[Room]:
    """A row of glass-walled rooms sharing a wall. `names` is (name, capacity,
    height-weight); widths are split evenly across the strip."""
    each = (w - gap * (len(names) - 1)) / len(names)
    out = []
    for i, (name, capacity, h) in enumerate(names):
        out.append(
            Room(name, Rect(x + i * (each + gap), y, each, h), capacity=capacity)
        )
    return out


def label_desks(
    points: list[tuple[float, float]],
    floor: str,
    letter: str,
    zone: str,
    *,
    start: int = 1,
    window_x: tuple[float, float] | None = None,
) -> list[Desk]:
    """Name and attribute a run of seats. `4F-A-01` is the convention the
    plan editor bulk-places with (PRD FR-8.2, TDD §8.4)."""
    out = []
    for i, (x, y) in enumerate(points):
        n = start + i
        out.append(
            Desk(
                name=f"{floor}-{letter}-{n:02d}",
                x=x,
                y=y,
                zone=zone,
                window=bool(window_x and (x < window_x[0] or x > window_x[1])),
                accessible=n % 12 == 1,
                sit_stand=n % 3 == 0,
                monitors=1 if n % 4 == 0 else 2,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Archetypes
# ---------------------------------------------------------------------------


def bank_floor(
    key: str,
    site: str,
    name: str,
    ordinal: int,
    *,
    banks: int,
    pods_per_bank: int,
    seats: int,
    zone_of_bank: list[str],
) -> FloorPlan:
    """The big open plate: parallel banks of benching, rooms and core down one
    side. This is the archetype the 300-desk performance budget assumes
    (PRD §9.1) -- it is the densest thing a real office does."""
    margin_x, margin_y = 96, 186
    pod_w, pod_h = bench_w(seats), bench_h()
    bank_pitch = pod_w + 58
    pod_pitch = pod_h + 66

    desk_area_w = banks * bank_pitch - 58
    desk_area_h = pods_per_bank * pod_pitch - 66

    core_w = 340
    width = int(margin_x * 2 + desk_area_w + 40 + core_w)
    height = int(margin_y + desk_area_h + 130)

    plate = Rect(0, 0, width, height)
    benches: list[Rect] = []
    desks: list[Desk] = []

    for b in range(banks):
        letter = chr(ord("A") + b)
        x0 = margin_x + BENCH_PAD_X + b * bank_pitch
        seats_here: list[tuple[float, float]] = []
        for p in range(pods_per_bank):
            y0 = margin_y + BENCH_PAD_Y + p * pod_pitch
            slab, points = bench(x0, y0, seats)
            benches.append(slab)
            seats_here.extend(points)
        desks.extend(
            label_desks(
                seats_here,
                name,
                letter,
                zone_of_bank[b],
                window_x=(margin_x + 200, margin_x + desk_area_w - 200),
            )
        )

    # Rooms along the top edge, above the benching; core down the right.
    rooms = meeting_strip(
        margin_x,
        34,
        desk_area_w,
        [("Kepler", 12, 92), ("Curie", 8, 92), ("Turing", 6, 92), ("Hopper", 6, 92)],
    )
    core_x = margin_x + desk_area_w + 40
    rooms += [
        Room("Lifts", Rect(core_x, 34, core_w, 150), kind="core"),
        Room("Stairs", Rect(core_x, 198, core_w / 2 - 7, 110), kind="core"),
        Room("WC", Rect(core_x + core_w / 2 + 7, 198, core_w / 2 - 7, 110), kind="wc"),
        Room("Kitchen", Rect(core_x, 322, core_w, 210), kind="cafe"),
        Room("Lounge", Rect(core_x, 546, core_w, 230), kind="collab"),
        Room("Booth 1", Rect(core_x, 790, core_w / 2 - 7, 96), capacity=2, kind="focus"),
        Room("Booth 2", Rect(core_x + core_w / 2 + 7, 790, core_w / 2 - 7, 96),
             capacity=2, kind="focus"),
    ]

    zones = []
    seen: dict[str, tuple[float, float]] = {}
    for b, zone_name in enumerate(zone_of_bank):
        x0 = margin_x + b * bank_pitch
        lo, hi = seen.get(zone_name, (x0, x0 + pod_w))
        seen[zone_name] = (min(lo, x0), max(hi, x0 + pod_w))
    for zone_name, (lo, hi) in seen.items():
        zones.append(
            Zone(zone_name, Rect(lo - 20, margin_y - 30, hi - lo + 40, desk_area_h + 64))
        )

    return FloorPlan(
        key=key, site=site, name=name, ordinal=ordinal, width=width, height=height,
        outline=[plate], zones=zones, rooms=rooms, desks=desks, benches=benches,
    )


def spine_floor(
    key: str, site: str, name: str, ordinal: int, *, pods_per_side: int, seats: int,
    room_names: list[str],
) -> FloorPlan:
    """A central circulation spine with benching either side and the rooms
    bookending it. Narrower plate, so every desk is within a few metres of a
    window -- which is why European floors tend to look like this."""
    margin_x, margin_y = 90, 128
    pod_w, pod_h = bench_w(seats), bench_h()
    pod_pitch = pod_w + 56
    spine_h = 108

    desk_area_w = pods_per_side * pod_pitch - 56
    width = int(margin_x * 2 + desk_area_w)
    height = int(margin_y + pod_h * 2 + spine_h + 190)

    north_y = margin_y + BENCH_PAD_Y
    south_y = margin_y + pod_h + spine_h + BENCH_PAD_Y

    benches: list[Rect] = []
    north: list[tuple[float, float]] = []
    south: list[tuple[float, float]] = []
    for p in range(pods_per_side):
        x0 = margin_x + BENCH_PAD_X + p * pod_pitch
        slab, points = bench(x0, north_y, seats)
        benches.append(slab)
        north.extend(points)
        slab, points = bench(x0, south_y, seats)
        benches.append(slab)
        south.extend(points)

    desks = label_desks(north, name, "N", "Engineering")
    desks += label_desks(south, name, "S", "Design")

    body_bottom = margin_y + pod_h * 2 + spine_h
    rooms = meeting_strip(
        margin_x, 30, desk_area_w,
        [(room_names[0], 10, 84), (room_names[1], 6, 84), (room_names[2], 4, 84)],
    )
    rooms += [
        Room("Kitchen", Rect(margin_x, body_bottom + 30, desk_area_w * 0.42, 130), kind="cafe"),
        Room(
            "Lounge",
            Rect(margin_x + desk_area_w * 0.46, body_bottom + 30, desk_area_w * 0.32, 130),
            kind="collab",
        ),
        Room(
            "Focus",
            Rect(margin_x + desk_area_w * 0.82, body_bottom + 30, desk_area_w * 0.18, 130),
            capacity=2,
            kind="focus",
        ),
        Room("Lifts", Rect(margin_x + desk_area_w / 2 - 110, margin_y + pod_h + 14, 220, 80),
             kind="core"),
    ]

    zones = [
        Zone("Engineering", Rect(margin_x - 18, margin_y - 30, desk_area_w + 36, pod_h + 44)),
        Zone(
            "Design",
            Rect(margin_x - 18, margin_y + pod_h + spine_h - 14, desk_area_w + 36, pod_h + 44),
        ),
    ]

    return FloorPlan(
        key=key, site=site, name=name, ordinal=ordinal, width=width, height=height,
        outline=[Rect(0, 0, width, height)], zones=zones, rooms=rooms,
        desks=desks, benches=benches,
    )


def courtyard_floor(
    key: str, site: str, name: str, ordinal: int, *, seats: int, per_row: int
) -> FloorPlan:
    """A doughnut: benching north and south of a central atrium, rooms east
    and west of it. The void is the point -- it is what lets a plate this deep
    still have daylight in the middle of it."""
    margin = 110
    pod_w, pod_h = bench_w(seats), bench_h()
    gap_x, gap_y = 60, 74
    atrium_w, atrium_h = 420, 300

    row_w = per_row * pod_w + (per_row - 1) * gap_x
    width = int(margin * 2 + row_w)
    height = int(margin + pod_h + gap_y + atrium_h + gap_y + pod_h + 190)

    atrium = Rect((width - atrium_w) / 2, margin + pod_h + gap_y, atrium_w, atrium_h)

    benches: list[Rect] = []
    north: list[tuple[float, float]] = []
    south: list[tuple[float, float]] = []
    for i in range(per_row):
        x0 = margin + BENCH_PAD_X + i * (pod_w + gap_x)
        slab, points = bench(x0, margin + BENCH_PAD_Y, seats)
        benches.append(slab)
        north.extend(points)
        slab, points = bench(x0, atrium.bottom + gap_y + BENCH_PAD_Y, seats)
        benches.append(slab)
        south.extend(points)

    desks = label_desks(north, name, "N", "Engineering")
    desks += label_desks(south, name, "S", "Sales")

    # The strips either side of the atrium, which is what the void leaves.
    side_w = atrium.x - margin - 26
    east_x = atrium.right + 26
    body_bottom = atrium.bottom + gap_y + pod_h

    rooms = [
        Room("Shard", Rect(margin, atrium.y, side_w, 140), capacity=8),
        Room("Thames", Rect(margin, atrium.y + 156, side_w, atrium_h - 156), capacity=4),
        Room("Lifts", Rect(east_x, atrium.y, side_w, 140), kind="core"),
        Room("WC", Rect(east_x, atrium.y + 156, side_w, atrium_h - 156), kind="wc"),
        Room("Kitchen", Rect(margin, body_bottom + 34, row_w * 0.55, 120), kind="cafe"),
        Room("Booth", Rect(margin + row_w * 0.6, body_bottom + 34, row_w * 0.18, 120),
             capacity=2, kind="focus"),
        Room("Lounge", Rect(margin + row_w * 0.82, body_bottom + 34, row_w * 0.18, 120),
             kind="collab"),
    ]

    zones = [
        Zone("Engineering", Rect(margin - 20, margin - 28, row_w + 40, pod_h + 56)),
        Zone(
            "Sales",
            Rect(margin - 20, atrium.bottom + gap_y - 28, row_w + 40, pod_h + 56),
        ),
    ]

    return FloorPlan(
        key=key, site=site, name=name, ordinal=ordinal, width=width, height=height,
        outline=[Rect(0, 0, width, height)], zones=zones, rooms=rooms,
        desks=desks, benches=benches, voids=[atrium],
    )


def wings_floor(
    key: str, site: str, name: str, ordinal: int, *, seats: int, wing_pods: int,
    stub_pods: int,
) -> FloorPlan:
    """An L: a long upper wing and a narrower stub running off it. Two outline
    rects rather than one, which is the whole reason `outline` is a list.

    The invariant the geometry has to keep is simple and easy to break: below
    the wing, nothing may sit right of the stub. Everything here is derived
    from `stub_w` for that reason.
    """
    margin = 100
    pod_w, pod_h = bench_w(seats), bench_h()
    pitch = pod_w + 56
    core_w = 320

    wing_desks_w = wing_pods * pitch - 56
    width = int(margin * 2 + wing_desks_w + 50 + core_w)
    wing_h = 430

    stub_desks_w = stub_pods * pitch - 56
    stub_w = int(margin * 2 + stub_desks_w)
    stub_h = 472
    height = wing_h + stub_h

    benches: list[Rect] = []
    upper: list[tuple[float, float]] = []
    bench_y = 208
    for p in range(wing_pods):
        slab, points = bench(margin + BENCH_PAD_X + p * pitch, bench_y + BENCH_PAD_Y, seats)
        benches.append(slab)
        upper.extend(points)

    lower: list[tuple[float, float]] = []
    stub_bench_y = wing_h + 60
    for p in range(stub_pods):
        slab, points = bench(
            margin + BENCH_PAD_X + p * pitch, stub_bench_y + BENCH_PAD_Y, seats
        )
        benches.append(slab)
        lower.extend(points)

    desks = label_desks(upper, name, "A", "Engineering")
    desks += label_desks(lower, name, "B", "Sales")

    core_x = width - margin - core_w
    amenity_y = stub_bench_y + pod_h + 40
    rooms = meeting_strip(
        margin, 30, wing_desks_w,
        [("Marina", 10, 86), ("Raffles", 6, 86), ("Sentosa", 4, 86)],
    )
    rooms += [
        Room("Lifts", Rect(core_x, 140, core_w, 130), kind="core"),
        Room("WC", Rect(core_x, 284, core_w, 106), kind="wc"),
        Room("Kitchen", Rect(margin, amenity_y, stub_desks_w * 0.52, 160), kind="cafe"),
        Room("Terrace", Rect(margin + stub_desks_w * 0.56, amenity_y,
                             stub_desks_w * 0.26, 160), kind="collab"),
        Room("Booth", Rect(margin + stub_desks_w * 0.86, amenity_y,
                           stub_desks_w * 0.14, 160), capacity=2, kind="focus"),
    ]

    zones = [
        Zone("Engineering", Rect(margin - 20, bench_y - 28, wing_desks_w + 40, pod_h + 56)),
        Zone("Sales", Rect(margin - 20, stub_bench_y - 28, stub_desks_w + 40, pod_h + 56)),
    ]

    return FloorPlan(
        key=key, site=site, name=name, ordinal=ordinal, width=width, height=height,
        outline=[Rect(0, 0, width, wing_h), Rect(0, wing_h, stub_w, stub_h)],
        zones=zones, rooms=rooms, desks=desks, benches=benches,
    )


def loft_floor(
    key: str,
    site: str,
    name: str,
    ordinal: int,
    *,
    seats: int,
    pods: int,
    room_names: list[str],
    zone_name: str = "Everyone",
) -> FloorPlan:
    """A small floor that is mostly not desks. Two short banks, a big café and
    a lot of soft seating -- the shape a 40-person office actually takes, and
    the counterweight to the 300-desk plate."""
    margin = 96
    pod_w, pod_h = bench_w(seats), bench_h()
    pitch = pod_w + 60

    # `pods` is the total; they sit in two rows, so the plate is sized for
    # half of them. Sizing it for all four is what left Austin's desks in the
    # left half of an empty floor.
    per_row = pods // 2
    width = int(margin * 2 + per_row * pitch - 60)
    height = int(margin + pod_h * 2 + 96 + 330)

    benches: list[Rect] = []
    points: list[tuple[float, float]] = []
    for row in range(2):
        for p in range(per_row):
            x0 = margin + BENCH_PAD_X + p * pitch
            y0 = margin + 70 + BENCH_PAD_Y + row * (pod_h + 96)
            slab, pts = bench(x0, y0, seats)
            benches.append(slab)
            points.extend(pts)

    desks = label_desks(points, name, "A", zone_name)

    body_bottom = margin + 70 + pod_h * 2 + 96
    strip_w = width - margin * 2
    rooms = meeting_strip(
        margin, 24, strip_w,
        [(room_names[0], 8, 72), (room_names[1], 4, 72)],
    )
    rooms += [
        Room("Kitchen", Rect(margin, body_bottom + 40, strip_w * 0.46, 200), kind="cafe"),
        Room("Lounge", Rect(margin + strip_w * 0.5, body_bottom + 40, strip_w * 0.3, 200),
             kind="collab"),
        Room("Booth", Rect(margin + strip_w * 0.84, body_bottom + 40, strip_w * 0.16, 94),
             capacity=2, kind="focus"),
        Room("Lifts", Rect(margin + strip_w * 0.84, body_bottom + 146, strip_w * 0.16, 94),
             kind="core"),
    ]

    zones = [Zone(zone_name, Rect(margin - 20, margin + 40, strip_w + 40, pod_h * 2 + 140))]

    return FloorPlan(
        key=key, site=site, name=name, ordinal=ordinal, width=width, height=height,
        outline=[Rect(0, 0, width, height)], zones=zones, rooms=rooms,
        desks=desks, benches=benches,
    )


# ---------------------------------------------------------------------------
# The offices
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Office:
    name: str
    timezone: str
    #: Lat/lng for the check-in geofence (FR-4.3).
    lat: float
    lng: float
    #: In ordinal order, lowest first. An office with more than one is the
    #: normal case, not the interesting one -- a single-floor site is the
    #: small office, and the client hides the floor picker for it.
    floors: list[FloorPlan]

    @property
    def slug(self) -> str:
        return slugify(self.name)


def slugify(name: str) -> str:
    """Site name -> the stem of its photo and plan files. Must agree with
    `siteSlug` in client/src/booking/photos.ts."""
    out = []
    for ch in name.lower():
        out.append(ch if ch.isalnum() else "-")
    return "-".join(part for part in "".join(out).split("-") if part)


def _offices() -> list[Office]:
    return [
        Office(
            "Tampa", "America/New_York", 27.9506, -82.4572,
            [
                # 5 banks x 6 pods x 10 seats = 300, the PRD §9.1 budget.
                bank_floor(
                    "tampa-4f", "Tampa", "4F", 4,
                    banks=5, pods_per_bank=6, seats=5,
                    zone_of_bank=["Engineering", "Engineering", "Design", "Sales", "Quiet"],
                ),
                spine_floor("tampa-5f", "Tampa", "5F", 5, pods_per_side=4, seats=6,
                            room_names=["Gasparilla", "Ybor", "Bayshore"]),
            ],
        ),
        Office(
            "Berlin Mitte", "Europe/Berlin", 52.5200, 13.4050,
            [
                spine_floor("berlin-mitte-2f", "Berlin Mitte", "2F", 2,
                            pods_per_side=4, seats=6,
                            room_names=["Bauhaus", "Tiergarten", "Spree"]),
                loft_floor("berlin-mitte-3f", "Berlin Mitte", "3F", 3, seats=5, pods=4,
                           room_names=["Reichstag", "Kreuzberg"], zone_name="Design"),
            ],
        ),
        Office(
            "London Bridge", "Europe/London", 51.5045, -0.0865,
            [courtyard_floor("london-bridge-1f", "London Bridge", "1F", 1,
                             seats=5, per_row=3)],
        ),
        Office(
            "Singapore Raffles", "Asia/Singapore", 1.2830, 103.8513,
            [wings_floor("singapore-raffles-12f", "Singapore Raffles", "12F", 12,
                         seats=6, wing_pods=4, stub_pods=2)],
        ),
        Office(
            "Austin Domain", "America/Chicago", 30.4013, -97.7250,
            [loft_floor("austin-domain-1f", "Austin Domain", "1F", 1, seats=6, pods=4,
                        room_names=["Barton", "Congress"], zone_name="Everyone")],
        ),
        Office(
            "Denver Union", "America/Denver", 39.7527, -105.0000,
            [loft_floor("denver-union-3f", "Denver Union", "3F", 3, seats=5, pods=4,
                        room_names=["Front Range", "Platte"], zone_name="Everyone")],
        ),
    ]


#: The demo tenant's offices, in the order the seed creates them.
OFFICES: list[Office] = _offices()

OFFICE_BY_NAME: dict[str, Office] = {o.name: o for o in OFFICES}

#: Every floor in the tenant, flattened. What renders and what gets tested.
ALL_FLOORS: list[FloorPlan] = [floor for office in OFFICES for floor in office.floors]
