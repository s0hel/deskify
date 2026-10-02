from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from deskify_bot.floorplan import compose_svg, render_png, short_name
from deskify_bot.plan_images import LINK_TTL_S, PlanSource, Signer

PLANS = Path(__file__).resolve().parents[2] / "client" / "public" / "plans"
FLOOR = {"id": "f5", "name": "5F", "resources": [
    {"id": "d1", "kind": "desk", "name": "5F-N-01", "plan_x": 124.0, "plan_y": 166.0},
    {"id": "d2", "kind": "desk", "name": "5F-N-02", "plan_x": 188.0, "plan_y": 166.0},
    {"id": "d3", "kind": "desk", "name": "5F-N-03", "plan_x": 252.0, "plan_y": 166.0},
    {"id": "r1", "kind": "room", "name": "Huddle", "plan_x": 400.0, "plan_y": 70.0},
]}


def test_short_name_drops_only_the_floor_prefix():
    assert short_name("5F-N-03", "5F") == "N-03"
    assert short_name("Window 3", "5F") == "Window 3"


def test_only_free_and_mine_are_labelled():
    svg = compose_svg('<svg xmlns="http://www.w3.org/2000/svg"></svg>', FLOOR,
                      {"d1": "free", "d2": "booked", "d3": "mine"})
    assert ">N-01<" in svg and ">N-03<" in svg
    assert ">N-02<" not in svg
    assert ">Huddle<" in svg  # the plan leaves bookable rooms for the app to name


def test_dark_mode_block_is_stripped():
    plan = ('<svg xmlns="http://www.w3.org/2000/svg"><style>.slab{fill:#fff}'
            "@media (prefers-color-scheme: dark) { .slab { fill: #000; } .wall { stroke: #111; } }"
            "</style></svg>")
    svg = compose_svg(plan, FLOOR, {})
    assert "prefers-color-scheme" not in svg and ".slab{fill:#fff}" in svg


def test_renders_the_real_drawing_to_png():
    png = render_png((PLANS / "tampa-5f.svg").read_text(), FLOOR, {"d1": "free"})
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_signed_link_round_trips_and_binds_every_field():
    now = [1_000_000.0]
    s = Signer(b"k" * 32, clock=lambda: now[0])
    q = {k: v[0] for k, v in parse_qs(s.query("f5", date(2026, 10, 2), "priya@x")).items()}
    assert s.verify("f5", q["on"], q["u"], q["exp"], q["sig"])
    assert not s.verify("f6", q["on"], q["u"], q["exp"], q["sig"])
    assert not s.verify("f5", "2026-10-03", q["u"], q["exp"], q["sig"])
    assert not s.verify("f5", q["on"], "dana@x", q["exp"], q["sig"])
    assert not s.verify("f5", q["on"], q["u"], str(int(q["exp"]) + 1), q["sig"])
    assert not Signer(b"other" * 8, clock=lambda: now[0]).verify(
        "f5", q["on"], q["u"], q["exp"], q["sig"])


def test_signed_link_expires():
    now = [1_000_000.0]
    s = Signer(b"k" * 32, clock=lambda: now[0])
    q = {k: v[0] for k, v in parse_qs(s.query("f5", date(2026, 10, 2), "priya@x")).items()}
    now[0] += LINK_TTL_S + 1
    assert not s.verify("f5", q["on"], q["u"], q["exp"], q["sig"])
    assert not s.verify("f5", q["on"], q["u"], "not-a-number", q["sig"])


@pytest.mark.parametrize("key", ["../../etc/passwd", "a/b", "x.svg"])
async def test_plan_key_cannot_escape_the_plans_directory(key):
    assert await PlanSource(str(PLANS)).svg(key) is None


async def test_plan_source_reads_a_directory():
    assert (await PlanSource(str(PLANS)).svg("tampa-5f")).startswith("<svg")
