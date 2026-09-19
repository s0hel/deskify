# deskflow — Phase 0 skeleton

Flex workspace booking. See [docs/PRD.md](docs/PRD.md) and
[docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md).

**Stack:** React + Capacitor · FastAPI + Postgres.

---

## Quick start

```bash
make seed     # Postgres + migrations + a 300-desk demo tenant
make api      # API  -> http://localhost:8099  (/docs for OpenAPI)
make web      # app  -> http://localhost:5173
make test     # the full suite, both halves
```

The app signs in as `priya@northwind.example` automatically in dev, loads the seeded
Berlin site, and books against the real API. Tapping a free desk books it; tapping your
own booking cancels it. Both the plan and the list do this.

Tests run against a **separate** `deskflow_test` database, created and migrated on first
run, so `make test` never empties the tenant a running app is showing you.

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
| Client wired to the API: sign-in, real floors, booking, cancel | Done |
| Designed UI: tokens, Today hero, week strip, circle plan, bottom sheets | Done |
| Generated TypeScript client | Done — `client/src/api/schema.d.ts` |
| OIDC end to end for one IdP | **Blocked on IdP credentials** (T6) |
| 300-desk floor-plan spike on device | **Harness ready, gate not yet run on hardware** |
| Barcode scanning behind a transparent webview | **Not run — needs a device build** |
| OTA decision | **Open** (T1) |

The three unfinished rows are the ones that need a Mac with Xcode, an Android
device, and an IdP tenant. Everything that can be verified on a laptop is
verified and running.

---

## Configuration fails closed

`DESKFLOW_ENVIRONMENT` defaults to **`prod`**, not dev. Three things depend on it — the
JWT signing key, the database credentials, and `/auth/dev-sign-in`, which mints a token
for any user from an email alone. A forgotten variable must not hand out a published
signing key, a published database password, and a live auth bypass, so dev is an
explicit opt-in:

- the `make` targets export `DESKFLOW_ENVIRONMENT=dev`
- CI sets it for the test jobs
- `tests/conftest.py` sets it before anything imports `app.config`

Outside dev the API **refuses to start** if:

| Setting | Refused when |
|---|---|
| `DESKFLOW_JWT_SECRET` | it is the default in this repo, or under 32 characters |
| `DESKFLOW_DATABASE_URL` | it is the default in this repo, has no password, uses the username as the password, uses a placeholder (`changeme`, `postgres`, …), or the password is under 16 characters |

and `/auth/dev-sign-in` is not registered at all. The database check is about
credentials, not topology — a `localhost` database in production is fine.

Copy `api/.env.example` to `api/.env` for local work; it is gitignored and already
carries the dev defaults. For staging and production, generate real values:

```bash
openssl rand -base64 48
```

## Design

Tokens live at the top of `client/src/styles.css` — ground, surface, ink, muted, line,
accent, clay, and a state colour per resource state. Light is the designed theme; dark
holds the same hues and inverts only the surfaces.

Two patterns are worth knowing before changing anything:

- **The plan opens covered, not letterboxed.** `coverViewBox` gives the viewBox the
  *container's* aspect ratio, so the plan fills a tall phone screen and is panned, rather
  than sitting in a strip with dead space beneath it. Label visibility is judged by
  rendered pixel size, not a fraction of the plan.
- **A refusal offers a way forward.** `RefusalSheet` names the problem in plain language,
  then lists the nearest days that actually have space and lets you jump to one. FR-6.9
  asks the app to say which rule refused a booking; a refusal that only explains is still
  a dead end. The machine code sits in small type at the bottom, addressed to support
  rather than to the person reading it.

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
- **`test_dev_endpoint_isolation.py`** — starts real subprocesses and asserts
  `/auth/dev-sign-in` returns 404 in prod and staging, and that the app refuses to boot
  with the default signing key.

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
