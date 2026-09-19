# deskflow — Phase 0 skeleton

Flex workspace booking. See [docs/PRD.md](docs/PRD.md) and
[docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md).

**Stack:** React + Capacitor · FastAPI + Postgres.

---

## Quick start

```bash
make seed     # Postgres + migrations + a 300-desk demo tenant
make api      # http://localhost:8099  (/docs for OpenAPI)
make test     # the full suite, both halves
```

Sign in as `priya@northwind.example`.

---

## What Phase 0 delivers

| Deliverable | State |
|---|---|
| Repo, CI, Makefile | Done |
| Schema incl. the exclusion constraint | Done — `api/alembic/versions/0001_initial.py` |
| Policy engine, pure and explainable | Done — `api/app/policy.py` |
| Tenancy layer + schema-driven cross-tenant harness | Done |
| Booking write path, concurrency-proven | Done |
| React + Capacitor client, floor plan, list view | Done |
| Generated TypeScript client | Done — `client/src/api/schema.d.ts` |
| OIDC end to end for one IdP | **Blocked on IdP credentials** (T6) |
| 300-desk floor-plan spike on device | **Harness ready, gate not yet run on hardware** |
| Barcode scanning behind a transparent webview | **Not run — needs a device build** |
| OTA decision | **Open** (T1) |

The three unfinished rows are the ones that need a Mac with Xcode, an Android
device, and an IdP tenant. Everything that can be verified on a laptop is
verified and running.

---

## The tests that matter

Four carry disproportionate weight (TDD §16). They are the reason to trust the rest.

```bash
cd api && uv run pytest tests/test_concurrency.py -q
```

- **`test_concurrency.py`** — fires 25 simultaneous bookings at one desk and asserts
  exactly one wins. This is the proof the whole design rests on. It also covers
  half-day overlap, adjacent half-days *not* colliding, cancellation reopening a slot
  with no row deletion, completed bookings still blocking, and the capacity counter
  holding its cap under concurrency.
- **`test_cross_tenant.py`** — walks the live OpenAPI schema, authenticates as one org,
  and attempts to act on another's objects, asserting 404. Driven from the schema, so a
  new endpoint is covered the day it is added.
- **`test_policy.py`** — 15 tests, no database, 0.01s. The rules are pure functions.
- **`client/src/floorplan/accessibility.test.tsx`** — asserts everything bookable on the
  plan is bookable in the list. The list is the accessible path, not a fallback.

---

## The floor-plan performance gate (risk R8)

```bash
make spike      # then open /spike.html ON THE DEVICE
```

Measures first render and frame times against the real component with 300 desks,
and prints PASS/FAIL against PRD §9.1's budgets. It reports **INVALID** rather
than numbers if the page is not visible, because a backgrounded tab throttles
`requestAnimationFrame` to ~1Hz and would produce meaningless results.

**A laptop result does not close this gate.** Record the device and OS.

The component's five rules are documented at the top of
`client/src/floorplan/FloorPlan.tsx`. Break any of them and the cost only shows
up on real hardware.

---

## Layout

```
api/
  app/
    models.py           schema (TDD §3)
    booking_service.py  the write path (TDD §4)
    policy.py           pure rules (TDD §4.3)
    repository.py       tenancy (TDD §15.1)
    timezone.py         the ONE day-boundary rule (TDD §3.4)
    routers/
  tests/
client/
  src/
    floorplan/          ONE component, viewer + editor (TDD §9)
    native/             every Capacitor call behind an interface (TDD §10.2)
    api/                generated client + problem+json handling
    admin/              lazily loaded (TDD §10.1)
  capacitor.config.ts   no server.url, deliberately
```

---

## Adding an endpoint

1. Fetch through `TenantRepository`. It refuses models not in `TENANT_SCOPED`.
2. Return 404, not 403, for another tenant's object.
3. Run `make test` — the cross-tenant harness picks the endpoint up automatically.
4. Run `make gen-api` and commit `client/src/api/schema.d.ts`; CI fails on drift.
