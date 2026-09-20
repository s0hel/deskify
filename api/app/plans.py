"""Render each floor in `app.floorplans` to an SVG. `make plans`.

The output goes to client/public/plans/<key>.svg, which Vite serves verbatim,
and `floor.plan_asset_key` names it. It is committed, so a clean checkout
builds without running Python; `tests/test_floorplans.py` fails if it has
drifted from the generator.

Two things about the drawing are not obvious:

**It is loaded with <image>, so it is an isolated document.** No CSS from the
app reaches it. That is deliberate -- the plan renders once and pan/zoom never
touches React (FloorPlan.tsx rule 1), and an inlined SVG would put a few
hundred more nodes into that tree for no benefit. The cost is that the theme
has to come from inside: the stylesheet below carries its own
`prefers-color-scheme` block. The app's manual `data-theme="light"` override
cannot reach it, so a reader who forces light while their OS is dark gets a
dark plan. Inline the file if that ever matters more than the render budget.

**Nothing here is interactive or labelled for assistive tech.** Desks are drawn
by FloorPlan.tsx on top of this; this is the room behind them. The whole SVG is
inside an aria-hidden element and the list view is the accessible path
(FR-10.5, TDD §9.4).
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

from app.floorplans import OFFICES, FloorPlan, Rect

OUT_DIR = Path(__file__).resolve().parents[2] / "client" / "public" / "plans"

# Architectural neutrals, not the app's accent palette: the plan is the room,
# and the desks drawn over it are the only thing that should carry state
# colour. Anything louder here competes with free/taken/yours.
STYLE = """
  .slab   { fill: #f4f2ed; }
  .void   { fill: #e6e2d8; }
  .wall   { fill: none; stroke: #43474e; stroke-width: 7; stroke-linejoin: round; }
  .bench  { fill: #e3dfd4; stroke: #d2cdbf; stroke-width: 2; }
  .room   { fill: #eae7f2; stroke: #c3bdd8; stroke-width: 3; }
  .room--core  { fill: #dcd8cf; stroke: #c3beb2; }
  .room--wc    { fill: #dcd8cf; stroke: #c3beb2; }
  .room--cafe  { fill: #f0e4d8; stroke: #ddc9b4; }
  .room--collab{ fill: #e2ecdf; stroke: #c4d8c0; }
  .room--focus { fill: #eae7f2; stroke: #c3bdd8; }
  .zone   { fill: none; stroke: #b9b3a5; stroke-width: 2; stroke-dasharray: 10 9; }
  .rlabel { fill: #5c6067; font: 600 19px system-ui, sans-serif; }
  .zlabel { fill: #8d8778; font: 700 15px system-ui, sans-serif;
            letter-spacing: 1.4px; text-transform: uppercase; }

  @media (prefers-color-scheme: dark) {
    .slab   { fill: #1e2127; }
    .void   { fill: #14161a; }
    .wall   { stroke: #767d88; }
    .bench  { fill: #272b32; stroke: #31363f; }
    .room   { fill: #2b2e39; stroke: #3d4152; }
    .room--core  { fill: #24272d; stroke: #343841; }
    .room--wc    { fill: #24272d; stroke: #343841; }
    .room--cafe  { fill: #322a26; stroke: #46392f; }
    .room--collab{ fill: #232d29; stroke: #324037; }
    .room--focus { fill: #2b2e39; stroke: #3d4152; }
    .zone   { stroke: #454a53; }
    .rlabel { fill: #9aa0a8; }
    .zlabel { fill: #6d7884; }
  }
"""


def _rect(r: Rect, cls: str, rx: float = 0) -> str:
    return (
        f'<rect class="{cls}" x="{_n(r.x)}" y="{_n(r.y)}" '
        f'width="{_n(r.w)}" height="{_n(r.h)}"'
        + (f' rx="{_n(rx)}"' if rx else "")
        + "/>"
    )


def _n(value: float) -> str:
    """Trim float noise, so a regenerated file diffs only where it changed."""
    rounded = round(value, 2)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)


def _text(x: float, y: float, cls: str, body: str, anchor: str = "middle") -> str:
    return (
        f'<text class="{cls}" x="{_n(x)}" y="{_n(y)}" text-anchor="{anchor}">'
        f"{escape(body)}</text>"
    )


def render(plan: FloorPlan) -> str:
    parts: list[str] = [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {plan.width} {plan.height}" '
            f'width="{plan.width}" height="{plan.height}">'
        ),
        f"<style>{STYLE}</style>",
    ]

    # Floorplate, then the voids cut out of it, then the rooms and furniture,
    # and the wall last so it reads over everything it encloses.
    parts.append('<g class="plate">')
    for rect in plan.outline:
        parts.append(_rect(rect, "slab"))
    for rect in plan.voids:
        parts.append(_rect(rect, "void", rx=10))
    parts.append("</g>")

    if plan.zones:
        parts.append('<g class="zones">')
        for zone in plan.zones:
            parts.append(_rect(zone.rect, "zone", rx=14))
            # Above the dashed box, not inside it: a 15px label set 22px below
            # the top edge sits ON the dash and gets cut by it.
            parts.append(_text(zone.rect.x + 6, zone.rect.y - 10, "zlabel", zone.name, "start"))
        parts.append("</g>")

    parts.append('<g class="rooms">')
    for room in plan.rooms:
        cls = "room" if room.kind == "meeting" else f"room room--{room.kind}"
        parts.append(_rect(room.rect, cls, rx=8))
        # The drawing names only what is NOT a resource. A bookable room is a
        # resource, and FloorPlan.tsx already draws its circle and its label
        # from the database -- labelling it here too put "Booth" on the plan
        # twice, once from each side.
        if not room.bookable:
            parts.append(_text(room.rect.cx, room.rect.cy + 7, "rlabel", room.name))
    parts.append("</g>")

    parts.append('<g class="benches">')
    for slab in plan.benches:
        parts.append(_rect(slab, "bench", rx=8))
    parts.append("</g>")

    parts.append('<g class="walls">')
    for rect in plan.outline:
        parts.append(_rect(rect, "wall"))
    parts.append("</g>")

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_all(out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for office in OFFICES:
        path = out_dir / f"{office.floor.key}.svg"
        path.write_text(render(office.floor))
        written.append(path)
    return written


def main() -> None:
    check = "--check" in sys.argv
    stale = []
    for office in OFFICES:
        path = OUT_DIR / f"{office.floor.key}.svg"
        want = render(office.floor)
        if check:
            if not path.exists() or path.read_text() != want:
                stale.append(path.name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(want)
        print(f"  {path.relative_to(OUT_DIR.parents[2])}  "
              f"{office.floor.width}x{office.floor.height}  "
              f"{office.floor.desk_count} desks")

    if check and stale:
        print("stale plan SVGs, run `make plans`: " + ", ".join(stale), file=sys.stderr)
        raise SystemExit(1)
    if check:
        print(f"{len(OFFICES)} plan SVGs up to date")


if __name__ == "__main__":
    main()
