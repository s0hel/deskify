"""Render each floor in `app.floorplans` to an SVG. `make plans`.

The output goes to client/public/plans/<key>.svg, which Vite serves verbatim,
and `floor.plan_asset_key` names it. It is committed, so a clean checkout
builds without running Python; `tests/test_floorplans.py` fails if it has
drifted from the generator.

The drawing is an architectural plan, not a diagram: thick exterior walls with
glazing and columns, rooms with walls and doors, and furniture in every room --
desks, chairs and monitors on the benches, tables and chairs in meeting rooms,
counters in kitchens, lifts and stairs in the core. ALL of it is derived from
the layout in app.floorplans. Nothing here moves a desk or a room: those
coordinates are in the database (app/seed.py copies them), so the drawing has
to fit around them, never the other way round.

Three things about the drawing are not obvious:

**It is loaded with <image>, so it is an isolated document.** No CSS from the
app reaches it. That is deliberate -- the plan renders once and pan/zoom never
touches React (FloorPlan.tsx rule 1), and an inlined SVG would put a few
thousand more nodes into that tree for no benefit. The cost is that the theme
has to come from inside: the stylesheet below carries its own
`prefers-color-scheme` block. The app's manual `data-theme="light"` override
cannot reach it, so a reader who forces light while their OS is dark gets a
dark plan. Inline the file if that ever matters more than the render budget.

**The desk's state circle sits on the desk's own seat.** FloorPlan.tsx draws a
circle of DESK_R at each desk's point, so the furniture is laid out around that
point: the worksurface runs from it towards the bench's spine, the chair sits
just outside it, and both show past the circle's edge. The circle is the one
thing on the plan that carries state colour; the furniture uses muted tones so
it never competes with free/taken/yours.

**Nothing here is interactive or labelled for assistive tech.** Desks are drawn
by FloorPlan.tsx on top of this; this is the room behind them. The whole SVG is
inside an aria-hidden element and the list view is the accessible path
(FR-10.5, TDD §9.4).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from app.floorplans import ALL_FLOORS, DESK_R, ROOM_R, FloorPlan, Rect, Room

OUT_DIR = Path(__file__).resolve().parents[2] / "client" / "public" / "plans"

#: Exterior wall thickness. Drawn INSIDE the plate, so it never clips at the
#: viewBox edge and never reaches a desk (the nearest sits ~90px in).
WALL_T = 14
#: Interior partitions.
PARTITION_T = 5
#: Structural columns along the facade, at most this far apart.
COLUMN_PITCH = 260
COLUMN_S = 22

# Room fills follow the usual plan legend -- yellow meeting rooms, green
# conference rooms, orange kitchens, blue washrooms, grey core -- but at pastel
# strength. The desks drawn over the plan are the only thing that should carry
# full-strength colour.
STYLE = """
  .slab   { fill: #f4efe7; }
  .tiles  { fill: none; stroke: #ebe4d8; stroke-width: 1; }
  .carpet { fill: #eee7dc; }
  .void   { fill: #dfe6ee; }
  .rail   { fill: none; stroke: #9fc4e6; stroke-width: 4; }
  .wall   { fill: none; stroke: #2f3747; stroke-width: 14; stroke-linecap: square; }
  .glass  { fill: none; stroke: #b9d6ef; stroke-width: 6; }
  .glass-in { fill: none; stroke: #6f9cc6; stroke-width: 1.5; }
  .column { fill: #2f3747; }
  .part   { fill: none; stroke: #4a5468; stroke-width: 5; stroke-linecap: square; }
  .part-glass { fill: none; stroke: #8db6dc; stroke-width: 4; }
  .door   { fill: none; stroke: #4a5468; stroke-width: 1.5; }
  .swing  { fill: none; stroke: #8b94a3; stroke-width: 1.2; stroke-dasharray: 4 3; }
  .room--meeting    { fill: #f8eac0; }
  .room--conference { fill: #dcecd6; }
  .room--focus      { fill: #e6def2; }
  .room--cafe       { fill: #f6d9c2; }
  .room--collab     { fill: #efe5cf; }
  .room--core       { fill: #d9dde4; }
  .room--wc         { fill: #d5e6f4; }
  .desktop  { fill: #ffffff; stroke: #cdc5b8; stroke-width: 1.2; }
  .screen   { fill: #c9c1b3; }
  .monitor  { fill: #39414f; }
  .chair    { fill: #75849b; }
  .chair-back { fill: #56647a; }
  .table    { fill: #c89f72; stroke: #a7805a; stroke-width: 1.5; }
  .counter  { fill: #e3ddd2; stroke: #b9b1a3; stroke-width: 1.2; }
  .appliance{ fill: #c6ced8; stroke: #8e98a6; stroke-width: 1.2; }
  .hob      { fill: none; stroke: #3a3f48; stroke-width: 1.5; }
  .sofa     { fill: #8f97a3; stroke: #747c88; stroke-width: 1.2; }
  .rug      { fill: #e4d3b6; }
  .lift     { fill: #c4cad3; stroke: #4a5468; stroke-width: 1.5; }
  .lift-x   { fill: none; stroke: #7d8696; stroke-width: 1.2; }
  .tread    { fill: none; stroke: #9aa3b1; stroke-width: 1.2; }
  .fixture  { fill: #ffffff; stroke: #8e98a6; stroke-width: 1.2; }
  .stall    { fill: none; stroke: #8e98a6; stroke-width: 2; }
  .leaf     { fill: #5a9e5f; }
  .leaf-dk  { fill: #3f7f48; }
  .pot      { fill: #bca88d; }
  .pill     { fill: #ffffff; fill-opacity: 0.88; }
  .rlabel { fill: #4a5262; font: 600 17px system-ui, sans-serif; }
  .zlabel { fill: #7d8798; font: 700 15px system-ui, sans-serif;
            letter-spacing: 1.4px; text-transform: uppercase; }

  @media (prefers-color-scheme: dark) {
    .slab   { fill: #151b26; }
    .tiles  { stroke: #1b2230; }
    .carpet { fill: #19202c; }
    .void   { fill: #0a0e16; }
    .rail   { stroke: #34587a; }
    .wall   { stroke: #8492a8; }
    .glass  { stroke: #2c4a66; }
    .glass-in { stroke: #4f7aa3; }
    .column { fill: #8492a8; }
    .part   { stroke: #5d6a80; }
    .part-glass { stroke: #3d6488; }
    .door   { stroke: #6d7a90; }
    .swing  { stroke: #4b5568; }
    .room--meeting    { fill: #2c2717; }
    .room--conference { fill: #18271a; }
    .room--focus      { fill: #231f30; }
    .room--cafe       { fill: #2e2119; }
    .room--collab     { fill: #262217; }
    .room--core       { fill: #1c212b; }
    .room--wc         { fill: #172433; }
    .desktop  { fill: #2a3242; stroke: #384256; }
    .screen   { fill: #3a4354; }
    .monitor  { fill: #0c1018; }
    .chair    { fill: #4a5568; }
    .chair-back { fill: #3a4455; }
    .table    { fill: #5c4630; stroke: #6f5639; }
    .counter  { fill: #2b3240; stroke: #3c4558; }
    .appliance{ fill: #2f3746; stroke: #4b5568; }
    .hob      { stroke: #8a94a6; }
    .sofa     { fill: #3c4454; stroke: #4b5466; }
    .rug      { fill: #2e2a22; }
    .lift     { fill: #262c38; stroke: #5d6a80; }
    .lift-x   { stroke: #4b5568; }
    .tread    { stroke: #3c4558; }
    .fixture  { fill: #2a3242; stroke: #4b5568; }
    .stall    { stroke: #4b5568; }
    .leaf     { fill: #3c7343; }
    .leaf-dk  { fill: #2c5a33; }
    .pot      { fill: #5b4f40; }
    .pill     { fill: #151b26; }
    .rlabel { fill: #a3aec0; }
    .zlabel { fill: #6b7890; }
  }
"""

# Reused furniture, drawn once and placed with <use>. A chair faces +y: its
# back is at the top, the seat opens downwards towards whatever it is pulled
# up to.
DEFS = """<defs>
<g id="chair"><rect class="chair" x="-11" y="-9" width="22" height="19" rx="6"/><rect class="chair-back" x="-12" y="-13" width="24" height="7" rx="3.5"/></g>
<g id="plant"><circle class="pot" r="9"/><ellipse class="leaf" cx="0" cy="-8" rx="5" ry="10"/><ellipse class="leaf" cx="0" cy="-8" rx="5" ry="10" transform="rotate(72)"/><ellipse class="leaf" cx="0" cy="-8" rx="5" ry="10" transform="rotate(144)"/><ellipse class="leaf" cx="0" cy="-8" rx="5" ry="10" transform="rotate(216)"/><ellipse class="leaf" cx="0" cy="-8" rx="5" ry="10" transform="rotate(288)"/><circle class="leaf-dk" r="5"/></g>
<pattern id="tiles" width="40" height="40" patternUnits="userSpaceOnUse"><path class="tiles" d="M40 0H0V40"/></pattern>
</defs>"""


def _n(value: float) -> str:
    """Trim float noise, so a regenerated file diffs only where it changed."""
    rounded = round(value, 2)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)


def _rect(r: Rect, cls: str, rx: float = 0) -> str:
    return _box(r.x, r.y, r.w, r.h, cls, rx)


def _box(x: float, y: float, w: float, h: float, cls: str, rx: float = 0) -> str:
    return (
        f'<rect class="{cls}" x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"'
        + (f' rx="{_n(rx)}"' if rx else "")
        + "/>"
    )


def _line(x1: float, y1: float, x2: float, y2: float, cls: str) -> str:
    return f'<path class="{cls}" d="M{_n(x1)} {_n(y1)}L{_n(x2)} {_n(y2)}"/>'


def _use(ref: str, x: float, y: float, rotate: float = 0) -> str:
    rot = f" rotate({_n(rotate)})" if rotate else ""
    return f'<use href="#{ref}" transform="translate({_n(x)} {_n(y)}){rot}"/>'


def _text(x: float, y: float, cls: str, body: str, anchor: str = "middle") -> str:
    return (
        f'<text class="{cls}" x="{_n(x)}" y="{_n(y)}" text-anchor="{anchor}">'
        f"{escape(body)}</text>"
    )


def _label(cx: float, cy: float, body: str) -> list[str]:
    """A room's name on a pill, so it reads over whatever is drawn under it."""
    w = len(body) * 9.6 + 22
    return [
        _box(cx - w / 2, cy - 14, w, 27, "pill", rx=13.5),
        _text(cx, cy + 6, "rlabel", body),
    ]


def _overlaps(a: Rect, b: Rect) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


def _grow(r: Rect, by: float) -> Rect:
    return Rect(r.x - by, r.y - by, r.w + 2 * by, r.h + 2 * by)


def _inside(plan: FloorPlan, x: float, y: float) -> bool:
    return any(r.x <= x <= r.right and r.y <= y <= r.bottom for r in plan.outline)


# ---------------------------------------------------------------------------
# The shell: exterior walls, glazing and columns.
# ---------------------------------------------------------------------------


def outline_edges(outline: list[Rect]) -> list[tuple[float, float, float, float, int, int]]:
    """The boundary of the union of the outline rects, as merged straight
    segments (x1, y1, x2, y2, nx, ny) with the outward normal.

    Stroking each rect separately drew a wall straight across the inside of
    an L where its two rects meet. Only the true perimeter is a wall.
    """
    xs = sorted({v for r in outline for v in (r.x, r.right)})
    ys = sorted({v for r in outline for v in (r.y, r.bottom)})

    def filled(i: int, j: int) -> bool:
        if not (0 <= i < len(xs) - 1 and 0 <= j < len(ys) - 1):
            return False
        cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
        return any(r.x <= cx <= r.right and r.y <= cy <= r.bottom for r in outline)

    raw: list[tuple[float, float, float, float, int, int]] = []
    for j, y in enumerate(ys):
        for i in range(len(xs) - 1):
            above, below = filled(i, j - 1), filled(i, j)
            if above != below:
                raw.append((xs[i], y, xs[i + 1], y, 0, -1 if below else 1))
    for i, x in enumerate(xs):
        for j in range(len(ys) - 1):
            left, right = filled(i - 1, j), filled(i, j)
            if left != right:
                raw.append((x, ys[j], x, ys[j + 1], -1 if right else 1, 0))

    merged: list[tuple[float, float, float, float, int, int]] = []
    for seg in raw:
        if merged:
            x1, y1, x2, y2, nx, ny = merged[-1]
            if (nx, ny) == seg[4:] and (x2, y2) == seg[:2]:
                merged[-1] = (x1, y1, seg[2], seg[3], nx, ny)
                continue
        merged.append(seg)
    return merged


def _shell(plan: FloorPlan) -> list[str]:
    walls: list[str] = []
    glass: list[str] = []
    columns: list[str] = []
    half = WALL_T / 2
    for x1, y1, x2, y2, nx, ny in outline_edges(plan.outline):
        # The wall's centreline, inset by half its thickness.
        ox, oy = -nx * half, -ny * half
        ax, ay, bx, by = x1 + ox, y1 + oy, x2 + ox, y2 + oy
        walls.append(_line(ax, ay, bx, by, "wall"))

        length = math.hypot(bx - ax, by - ay)
        bays = max(1, math.ceil(length / COLUMN_PITCH))
        ux, uy = (bx - ax) / length, (by - ay) / length
        for k in range(bays + 1):
            t = length * k / bays
            cx, cy = ax + ux * t, ay + uy * t
            columns.append(_box(cx - COLUMN_S / 2, cy - COLUMN_S / 2, COLUMN_S, COLUMN_S, "column"))
            if k == bays:
                continue
            # Glazing fills the bay between two columns, short of each.
            s, e = t + COLUMN_S / 2 + 10, length * (k + 1) / bays - COLUMN_S / 2 - 10
            if e - s < 30:
                continue
            gx1, gy1 = ax + ux * s, ay + uy * s
            gx2, gy2 = ax + ux * e, ay + uy * e
            glass.append(_line(gx1, gy1, gx2, gy2, "glass"))
            glass.append(_line(gx1, gy1, gx2, gy2, "glass-in"))
    return ['<g class="walls">', *walls, *glass, *columns, "</g>"]


# ---------------------------------------------------------------------------
# Rooms. Each is drawn in a local frame W wide and D deep with its door on the
# bottom edge (v = D), then rotated into place -- so one set of furniture
# rules serves a room whichever way it faces.
# ---------------------------------------------------------------------------

_SIDES = {
    # side: (rotation, local W is the rect's w?)
    "bottom": (0, True),
    "top": (180, True),
    "left": (90, False),
    "right": (-90, False),
}


def door_side(room: Room, plan: FloorPlan) -> str:
    """The side with the most open floor in front of it -- the one that faces
    the floor, not the facade or the room next door."""
    r = room.rect
    others = [o.rect for o in plan.rooms if o is not room] + list(plan.voids)

    def clearance(side: str) -> float:
        best = 0.0
        for step in range(4, 240, 4):
            if side == "bottom":
                probe = Rect(r.x + 8, r.bottom, r.w - 16, step)
            elif side == "top":
                probe = Rect(r.x + 8, r.y - step, r.w - 16, step)
            elif side == "left":
                probe = Rect(r.x - step, r.y + 8, step, r.h - 16)
            else:
                probe = Rect(r.right, r.y + 8, step, r.h - 16)
            corners = [(probe.x, probe.y), (probe.right, probe.y),
                       (probe.x, probe.bottom), (probe.right, probe.bottom)]
            if any(_overlaps(probe, o) for o in others) or not all(
                _inside(plan, x, y) for x, y in corners
            ):
                break
            best = step
        return best

    # Ties go to the long sides first: a door in the long wall is the usual
    # arrangement, and it leaves the far wall free for furniture.
    order = ["bottom", "top", "left", "right"] if r.w >= r.h else ["left", "right", "bottom", "top"]
    if max(r.w, r.h) > 1.3 * min(r.w, r.h):
        # An elongated room is entered from a long wall. Furniture is laid
        # out facing the door, so a door in the end wall turns the table and
        # stacks a lift lobby's cars into one.
        order = order[:2]
    return max(order, key=clearance)


def _room_kind(room: Room) -> str:
    if room.kind == "meeting":
        return "conference" if room.capacity >= 8 else "meeting"
    return room.kind


def _room(room: Room, plan: FloorPlan) -> tuple[list[str], list[str]]:
    """The room's drawing and, separately, its label -- labels go on top of
    everything, so a neighbour's furniture can never cover one."""
    r = room.rect
    side = door_side(room, plan)
    angle, along_w = _SIDES[side]
    W, D = (r.w, r.h) if along_w else (r.h, r.w)
    kind = _room_kind(room)

    out = [
        f'<g transform="translate({_n(r.cx)} {_n(r.cy)})'
        + (f" rotate({angle})" if angle else "")
        + f' translate({_n(-W / 2)} {_n(-D / 2)})">',
        _box(0, 0, W, D, f"room--{kind}"),
    ]
    out += _interior(room, kind, W, D)
    out += _partitions(room, kind, W, D)
    out.append("</g>")

    labels: list[str] = []
    # A bookable room is a resource: FloorPlan.tsx draws its circle and its
    # name from the database, so naming it here too would print it twice.
    if not room.bookable:
        labels += _label(r.cx, r.cy, room.name)
    return out, labels


def _partitions(room: Room, kind: str, W: float, D: float) -> list[str]:
    out = [
        _line(0, 0, W, 0, "part"),
        _line(0, 0, 0, D, "part"),
        _line(W, 0, W, D, "part"),
    ]
    if kind in ("cafe", "collab"):
        # Open to the floor: half the front wall is not there.
        gap = W * 0.5
        s = (W - gap) / 2
        out += [_line(0, D, s, D, "part"), _line(s + gap, D, W, D, "part")]
        return out
    if room.name == "Lifts":
        # The lift lobby IS the front; there is no door to it.
        out.append(_line(0, D, W, D, "part"))
        return out

    door = min(40.0, W * 0.4)
    hinge = W - 12 - door
    front = "part-glass" if kind in ("meeting", "conference", "focus") else "part"
    out += [_line(0, D, hinge, D, front), _line(hinge + door, D, W, D, front)]
    # The leaf stands open into the room, and the swing it sweeps.
    out.append(_line(hinge, D, hinge, D - door, "door"))
    out.append(
        f'<path class="swing" d="M{_n(hinge)} {_n(D - door)}'
        f"A{_n(door)} {_n(door)} 0 0 1 {_n(hinge + door)} {_n(D)}\"/>"
    )
    return out


def _interior(room: Room, kind: str, W: float, D: float) -> list[str]:
    if kind in ("meeting", "conference", "focus"):
        return _meeting(max(room.capacity, 2), W, D)
    if kind == "cafe":
        return _kitchen(W, D)
    if kind == "collab":
        return _lounge(W, D)
    if kind == "wc":
        return _washroom(W, D)
    if room.name == "Lifts":
        return _lifts(W, D)
    if room.name == "Stairs":
        return _stairs(W, D)
    return []


def _meeting(capacity: int, W: float, D: float) -> list[str]:
    """A table with the room's capacity in chairs round it. The room's circle
    (ROOM_R) sits on the table's middle, so the table is never smaller."""
    ends = 2 if capacity >= 8 else 0
    per_side = math.ceil((capacity - ends) / 2)
    tw = min(W - 2 * 56, max(per_side * 50 + 24, 2 * ROOM_R + 16))
    th = min(D - 2 * 40, max(46, 2 * ROOM_R + 8))
    tw, th = max(tw, 30), max(th, 24)
    tx, ty = (W - tw) / 2, (D - th) / 2 - 4
    out = [_box(tx, ty, tw, th, "table", rx=min(th / 2, 12))]
    pitch = tw / per_side
    for i in range(per_side):
        cx = tx + pitch * (i + 0.5)
        out.append(_use("chair", cx, ty - 14))
        if i < capacity - ends - per_side:
            out.append(_use("chair", cx, ty + th + 14, 180))
    if ends:
        out.append(_use("chair", tx - 14, ty + th / 2, -90))
        out.append(_use("chair", tx + tw + 14, ty + th / 2, 90))
    return out


def _kitchen(W: float, D: float) -> list[str]:
    out = [_box(8, 8, W - 16, 30, "counter", rx=3)]
    # Sink, hob, and the fridge at the end of the run.
    out.append(_box(W * 0.22, 13, 34, 20, "appliance", rx=4))
    hx = W * 0.5
    for dx, dy in ((0, 0), (16, 0), (0, 12), (16, 12)):
        out.append(f'<circle class="hob" cx="{_n(hx + dx)}" cy="{_n(17 + dy)}" r="5"/>')
    out.append(_box(W - 46, 8, 38, 36, "appliance", rx=3))

    # Round café tables, four chairs each, in whatever floor is left.
    top, pitch = 62, 92
    cols = max(1, int((W - 20) // pitch))
    rows = max(0, int((D - top - 10) // pitch)) or (1 if D - top >= 62 else 0)
    x0 = (W - (cols - 1) * pitch) / 2
    for row in range(rows):
        for col in range(cols):
            cx, cy = x0 + col * pitch, top + 30 + row * pitch
            out.append(f'<circle class="table" cx="{_n(cx)}" cy="{_n(cy)}" r="15"/>')
            out += [
                _use("chair", cx, cy - 26),
                _use("chair", cx, cy + 26, 180),
                _use("chair", cx - 26, cy, -90),
                _use("chair", cx + 26, cy, 90),
            ]
    return out


def _lounge(W: float, D: float) -> list[str]:
    out = [_box(W * 0.12, D * 0.22, W * 0.76, D * 0.6, "rug", rx=10)]
    sw = min(W * 0.6, 220)
    sx = (W - sw) / 2
    out.append(_box(sx, 12, sw, 34, "sofa", rx=8))
    out.append(_box(sx, 12, sw, 10, "sofa", rx=5))
    out.append(_box(W / 2 - 34, D * 0.5 - 14, 68, 30, "table", rx=6))
    for ax in (W / 2 - 74, W / 2 + 46):
        if D > 120:
            out.append(_box(ax, D * 0.5 + 32, 28, 28, "sofa", rx=7))
    out += [_use("plant", 22, 24), _use("plant", W - 22, 24)]
    return out


def _washroom(W: float, D: float) -> list[str]:
    out: list[str] = []
    depth = min(54, D * 0.5)
    stalls = max(1, int((W - 16) // 44))
    x0 = (W - stalls * 44) / 2
    for i in range(stalls):
        x = x0 + i * 44
        out.append(_line(x, 0, x, depth, "stall"))
        out.append(f'<ellipse class="fixture" cx="{_n(x + 22)}" cy="{_n(depth * 0.42)}" rx="9" ry="12"/>')
    out.append(_line(x0 + stalls * 44, 0, x0 + stalls * 44, depth, "stall"))
    out.append(_line(x0, depth, x0 + stalls * 44, depth, "stall"))
    return out


def _lifts(W: float, D: float) -> list[str]:
    """Cars at both ends of the lobby, leaving the middle for its name."""
    s = max(30, min(56, D - 26))
    per_end = max(1, int((W / 2 - 50) // (s + 8)))
    out: list[str] = []
    xs = [10 + i * (s + 8) for i in range(per_end)]
    xs += [W - 10 - s - i * (s + 8) for i in range(per_end)]
    for x in xs:
        out.append(_box(x, 8, s, s, "lift"))
        out.append(f'<path class="lift-x" d="M{_n(x)} 8L{_n(x + s)} {_n(8 + s)}'
                   f'M{_n(x + s)} 8L{_n(x)} {_n(8 + s)}"/>')
    return out


def _stairs(W: float, D: float) -> list[str]:
    out: list[str] = []
    mid = D / 2
    for x in range(14, int(W - 10), 11):
        out.append(_line(x, 8, x, mid - 3, "tread"))
        out.append(_line(x, mid + 3, x, D - 8, "tread"))
    out.append(_line(8, mid, W - 8, mid, "stall"))
    return out


# ---------------------------------------------------------------------------
# Desks. One worksurface, a chair and its monitors per seat, laid out around
# the point FloorPlan.tsx draws the desk's circle at.
# ---------------------------------------------------------------------------


def _desks(plan: FloorPlan) -> list[str]:
    out: list[str] = ['<g class="benches">']
    half = 30  # SEAT_DX is 64: a 4px gap between neighbours.
    for slab in plan.benches:
        out.append(_line(slab.x + 6, slab.cy, slab.right - 6, slab.cy, "door"))
    for desk in plan.desks:
        slab = next(
            (b for b in plan.benches if b.x <= desk.x <= b.right and b.y <= desk.y <= b.bottom),
            None,
        )
        # Towards the spine the bench shares with the row behind it.
        toward = 1 if slab is None or desk.y <= slab.cy else -1
        near, far = desk.y - toward * 12, desk.y + toward * 36
        top, bottom = min(near, far), max(near, far)
        out.append(_box(desk.x - half, top, 2 * half, bottom - top, "desktop", rx=3))
        # Monitors at the back of the desk, past the circle's edge.
        my = desk.y + toward * 28
        offsets = (-11, 11) if desk.monitors >= 2 else (0,)
        for dx in offsets:
            out.append(_box(desk.x + dx - 9, my - 2, 18, 4, "monitor", rx=1))
        out.append(_use("chair", desk.x, desk.y - toward * (DESK_R + 14), 0 if toward > 0 else 180))
    out.append("</g>")
    return out


# ---------------------------------------------------------------------------
# Planting, wherever it fits.
# ---------------------------------------------------------------------------


def _plants(plan: FloorPlan) -> list[str]:
    """Pot plants at the ends of benches and the corners of zones, wherever
    one clears every desk, room, bench and label. Deterministic, so a
    regenerated drawing does not churn."""
    candidates: list[tuple[float, float]] = []
    for b in plan.benches:
        candidates += [(b.x - 24, b.cy), (b.right + 24, b.cy)]
    for z in plan.zones:
        r = z.rect
        candidates += [(r.x + 22, r.y + 22), (r.right - 22, r.y + 22),
                       (r.x + 22, r.bottom - 22), (r.right - 22, r.bottom - 22)]

    blockers = [_grow(r.rect, 18) for r in plan.rooms]
    blockers += [_grow(b, 8) for b in plan.benches]
    blockers += [_grow(z.label_rect, 8) for z in plan.zones]
    blockers += [_grow(v, 18) for v in plan.voids]

    placed: list[tuple[float, float]] = []
    for x, y in candidates:
        me = Rect(x - 16, y - 16, 32, 32)
        if not all(_inside(plan, px, py) for px, py in
                   ((x - 16 - WALL_T, y - 16 - WALL_T), (x + 16 + WALL_T, y + 16 + WALL_T))):
            continue
        if any(_overlaps(me, b) for b in blockers):
            continue
        if any(math.hypot(x - d.x, y - d.y) < DESK_R + 40 for d in plan.desks):
            continue
        if any(math.hypot(x - px, y - py) < 150 for px, py in placed):
            continue
        placed.append((x, y))
    return ['<g class="plants">', *(_use("plant", x, y) for x, y in placed), "</g>"]


# ---------------------------------------------------------------------------


def render(plan: FloorPlan) -> str:
    parts: list[str] = [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {plan.width} {plan.height}" '
            f'width="{plan.width}" height="{plan.height}">'
        ),
        f"<style>{STYLE}</style>",
        DEFS,
    ]

    # Floor first, then everything standing on it, then the shell over the
    # lot, and the labels last so nothing covers a name.
    parts.append('<g class="plate">')
    for rect in plan.outline:
        parts.append(_rect(rect, "slab"))
        parts.append(f'<rect fill="url(#tiles)" x="{_n(rect.x)}" y="{_n(rect.y)}" '
                     f'width="{_n(rect.w)}" height="{_n(rect.h)}"/>')
    for zone in plan.zones:
        parts.append(_rect(zone.rect, "carpet", rx=14))
    for rect in plan.voids:
        parts.append(_rect(rect, "void", rx=10))
        parts.append(_rect(_grow(rect, -3), "rail", rx=8))
    parts.append("</g>")

    labels: list[str] = []
    parts.append('<g class="rooms">')
    for room in plan.rooms:
        drawing, label = _room(room, plan)
        parts += drawing
        labels += label
    parts.append("</g>")

    parts += _desks(plan)
    parts += _plants(plan)
    parts += _shell(plan)

    parts.append('<g class="labels">')
    for zone in plan.zones:
        # Outside the zone's box, not inside it, and above unless the zone says
        # below (app/floorplans.py Zone.label).
        parts.append(_text(zone.label_x, zone.label_baseline, "zlabel", zone.name,
                           zone.label_anchor))
    for rect in plan.voids:
        labels += _label(rect.cx, rect.cy, "Atrium")
    parts += labels
    parts.append("</g>")

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_all(out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for floor in ALL_FLOORS:
        path = out_dir / f"{floor.key}.svg"
        path.write_text(render(floor))
        written.append(path)
    return written


def main() -> None:
    check = "--check" in sys.argv
    stale = []
    for floor in ALL_FLOORS:
        path = OUT_DIR / f"{floor.key}.svg"
        want = render(floor)
        if check:
            if not path.exists() or path.read_text() != want:
                stale.append(path.name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(want)
        print(f"  {path.relative_to(OUT_DIR.parents[2])}  "
              f"{floor.width}x{floor.height}  {floor.desk_count} desks")

    if check and stale:
        print("stale plan SVGs, run `make plans`: " + ", ".join(stale), file=sys.stderr)
        raise SystemExit(1)
    if check:
        print(f"{len(ALL_FLOORS)} plan SVGs up to date")


if __name__ == "__main__":
    main()
