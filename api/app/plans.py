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

from app.floorplans import ALL_FLOORS, FloorPlan, Rect

OUT_DIR = Path(__file__).resolve().parents[2] / "client" / "public" / "plans"

# Architectural neutrals, not the app's accent palette: the plan is the room,
# and the desks drawn over it are the only thing that should carry state
# colour. Anything louder here competes with free/taken/yours.
STYLE = """
  .slab   { fill: #f6f9fc; }
  .void   { fill: #e2eaf4; }
  .wall   { fill: none; stroke: #37435a; stroke-width: 7; stroke-linejoin: round; }
  .bench  { fill: #e1e9f3; stroke: #cfdae8; stroke-width: 2; }
  .room   { fill: #e2ecfb; stroke: #bed2ee; stroke-width: 3; }
  .room--core  { fill: #dde4ee; stroke: #c6d0de; }
  .room--wc    { fill: #dde4ee; stroke: #c6d0de; }
  .room--cafe  { fill: #f6ecdb; stroke: #e2d0b3; }
  .room--collab{ fill: #ddefe7; stroke: #bfdccf; }
  .room--focus { fill: #e2ecfb; stroke: #bed2ee; }
  .zone   { fill: none; stroke: #aebbcd; stroke-width: 2; stroke-dasharray: 10 9; }
  .rlabel { fill: #5c6675; font: 600 19px system-ui, sans-serif; }
  .zlabel { fill: #8794a8; font: 700 15px system-ui, sans-serif;
            letter-spacing: 1.4px; text-transform: uppercase; }

  @media (prefers-color-scheme: dark) {
    .slab   { fill: #141a26; }
    .void   { fill: #0a0e17; }
    .wall   { stroke: #6d7b92; }
    .bench  { fill: #1e2533; stroke: #29313f; }
    .room   { fill: #1d2738; stroke: #2e3b52; }
    .room--core  { fill: #191f2b; stroke: #29313f; }
    .room--wc    { fill: #191f2b; stroke: #29313f; }
    .room--cafe  { fill: #2a2318; stroke: #3d3323; }
    .room--collab{ fill: #14251f; stroke: #20372c; }
    .room--focus { fill: #1d2738; stroke: #2e3b52; }
    .zone   { stroke: #3a465a; }
    .rlabel { fill: #97a3b6; }
    .zlabel { fill: #6b7890; }
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
