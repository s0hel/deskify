"""A fake Deskify API, in-process, via httpx.MockTransport.

Shaped like the real responses (api/app/routers/core.py) and no more. The
real API end to end is exercised by `make teams` + the Playground; these tests
pin the bot's own logic: who it signs in as, what it says when refused, and
which card follows which button.
"""

from __future__ import annotations

import json

import httpx
import pytest

from deskify_bot.config import BotSettings
from deskify_bot.deskify_client import DeskifyClient

TAMPA = {"id": "s-tampa", "name": "Tampa", "timezone": "America/New_York",
         "capacity_cap": None, "check_in_enabled": False}
BERLIN = {"id": "s-berlin", "name": "Berlin Mitte", "timezone": "Europe/Berlin",
          "capacity_cap": None, "check_in_enabled": False}


class FakeApi:
    def __init__(self):
        self.sign_ins: list[str] = []
        self.bookings: list[dict] = []
        self.taken: set[str] = set()
        self.calls: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        body = json.loads(request.content) if request.content else {}

        if path == "/auth/dev-sign-in":
            self.sign_ins.append(body["email"])
            if not body["email"].endswith("@northwind.example"):
                return httpx.Response(400, json={"code": "BAD_REQUEST", "detail": "unknown user"})
            return httpx.Response(200, json={"code": f"code-{body['email']}"})
        if path == "/auth/token":
            return httpx.Response(200, json={"access_token": f"tok-{body['code']}",
                                             "token_type": "bearer", "expires_in": 600})
        if path == "/me":
            return httpx.Response(200, json={"display_name": "Priya Raman", "home_site": TAMPA})
        if path == "/sites":
            return httpx.Response(200, json=[TAMPA, BERLIN])
        if path == "/sites/s-tampa/floors":
            return httpx.Response(200, json=[{"id": "f5", "name": "5F", "ordinal": 5,
                                              "free": 2, "total": 2}])
        if path in ("/sites/s-berlin/floors",):
            return httpx.Response(200, json=[])
        if path == "/floors/f5":
            return httpx.Response(200, json={"id": "f5", "name": "5F", "resources": [
                {"id": "d2", "kind": "desk", "name": "5F-N-02"},
                {"id": "d1", "kind": "desk", "name": "5F-N-01"},
                {"id": "r1", "kind": "room", "name": "Huddle"},
            ]})
        if path == "/floors/f5/state":
            return httpx.Response(200, json={"date": request.url.params["on"], "states": {
                "d1": "booked" if "d1" in self.taken else "free",
                "d2": "free", "r1": "free"}})
        if path == "/bookings" and method == "POST":
            if body["resource_id"] in self.taken:
                return httpx.Response(409, json={"code": "RESOURCE_TAKEN",
                                                 "title": "That resource was just taken"})
            self.taken.add(body["resource_id"])
            b = {"id": f"b{len(self.bookings) + 1}", "resource_id": body["resource_id"],
                 "user_id": "u", "local_date": body["on"], "status": "confirmed"}
            self.bookings.append(b)
            return httpx.Response(201, json=b)
        if path == "/bookings" and method == "GET":
            return httpx.Response(200, json=self.bookings)
        if path.startswith("/bookings/") and method == "DELETE":
            bid = path.rsplit("/", 1)[1]
            self.bookings = [b for b in self.bookings if b["id"] != bid]
            return httpx.Response(204)
        return httpx.Response(404, json={"code": "NOT_FOUND"})


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def client(api: FakeApi) -> DeskifyClient:
    http = httpx.AsyncClient(base_url="http://api", transport=httpx.MockTransport(api.handler))
    return DeskifyClient("http://api", http=http)


@pytest.fixture
def settings() -> BotSettings:
    return BotSettings(api_url="http://api", user_map={"aad-dana": "dana@northwind.example"})
