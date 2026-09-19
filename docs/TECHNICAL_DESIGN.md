# Technical Design Document — Flex Workspace Booking

**Product codename:** `deskflow`
**Status:** Draft v1.0
**Companion to:** [PRD.md](./PRD.md) (Draft v0.2, 2026-09-18)
**Last updated:** 2026-09-19

---

## 1. Scope and how to read this

This document specifies *how* the product described in the PRD is built. Where the PRD says what must
be true, this says which table, which constraint, which endpoint, which process.

The stack is fixed by PRD §8: **React + Capacitor** on the client, **FastAPI + Postgres** on the
server. The governing principle, carried over from that section, is to keep the implementation as
simple as it can be while still meeting the P0 requirements — which in practice means pushing
correctness into the database where the database is good at it, and refusing infrastructure until
measured load asks for it.

Three decisions drive most of the rest of the design:

1. **Double-booking is prevented by a Postgres exclusion constraint**, not by application locking
   (§4.1). This is the load-bearing decision; it removes an entire class of concurrency bug.
2. **Rooms are ordinary resources.** With no calendar integration, the room subsystem is the desk
   subsystem plus a timeline UI and an attendee list (§7).
3. **The client is one React codebase** serving the employee app (natively via Capacitor) and the
   admin console (on the web). The floor-plan viewer and the floor-plan editor are the same
   component (§9).

Requirement references like `FR-2.13` point at PRD §7. Where this document constrains a requirement
or reveals a limitation in it, that is called out explicitly rather than left implied.

---

## 2. Architecture at a glance

```
  ┌──────────────────────┐     ┌──────────────────────┐
  │  Employee app        │     │  Admin console       │
  │  React + Capacitor   │     │  React (web)         │
  │  iOS / Android       │     │  same codebase       │
  └──────────┬───────────┘     └──────────┬───────────┘
             │        HTTPS / JSON        │
             │   (generated TS client)    │
             └─────────────┬──────────────┘
                           ▼
              ┌────────────────────────────┐
              │  FastAPI  (stateless, N×)  │
              │  ─ request handlers        │
              │  ─ policy engine           │
              │  ─ repository layer (tenancy)
              └─────┬───────────────┬──────┘
                    │               │
                    ▼               ▼
          ┌──────────────┐   ┌──────────────┐
          │  Postgres    │   │ Object store │
          │  (single DB) │   │ floor plans, │
          │              │   │ QR PDFs      │
          └──────┬───────┘   └──────────────┘
                 │  job table (FOR UPDATE SKIP LOCKED)
                 ▼
          ┌──────────────┐        ┌─────────────────┐
          │  Worker (1×) │───────▶│ APNs/FCM, email │
          │  sweeps,     │        └─────────────────┘
          │  notifs,     │
          │  rollups     │
          └──────────────┘
```

Four runtime pieces: the API, the worker, Postgres, an object store. No Redis, no message broker, no
separate scheduler — see §12.1 for why, and for the tripwire that would change it.

The API is stateless and horizontally scalable. The worker is deliberately singular at launch; the
job table's locking makes running several safe if throughput demands it.

---

## 3. Data model

### 3.1 Conventions

- Every table carries `organization_id uuid NOT NULL`. No exceptions, including join tables — this
  makes the tenancy check uniform and makes a future move to row-level security mechanical (§15.2).
- Primary keys are `uuid` defaulting to `gen_random_uuid()` (built into Postgres 13+; no extension).
- Enumerations are `text` with a `CHECK` constraint, not native Postgres enum types. Adding a value
  to a native enum is a migration hazard and a lock; adding one to a `CHECK` is a trivial ALTER.
- All timestamps are `timestamptz`, stored UTC. Rendering timezone is a *site* property, never the
  device's (§3.4).
- Soft delete only where an audit trail needs it (users, resources). Everything else is hard-deleted.

### 3.2 Core tables

Abbreviated DDL — column lists are complete for the constraint-bearing tables and indicative
elsewhere. Full migrations live in `alembic/versions/`.

```sql
CREATE TABLE organization (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    region          text NOT NULL CHECK (region IN ('us','eu')),   -- §14.3
    settings        jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- FR-1.3 domain-based org discovery
CREATE TABLE email_domain (
    organization_id uuid NOT NULL REFERENCES organization(id),
    domain          text PRIMARY KEY,           -- globally unique: one domain, one tenant
    idp_kind        text NOT NULL CHECK (idp_kind IN ('google','entra','magic_link'))
);

CREATE TABLE app_user (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid NOT NULL REFERENCES organization(id),
    email               text NOT NULL,
    display_name        text NOT NULL,
    locale              text NOT NULL DEFAULT 'en',
    home_site_id        uuid REFERENCES site(id),
    presence_visibility text NOT NULL DEFAULT 'everyone'
                        CHECK (presence_visibility IN ('everyone','team','nobody')),  -- FR-5.6
    status              text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','deactivated')),
    UNIQUE (organization_id, email)
);

CREATE TABLE site (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  uuid NOT NULL REFERENCES organization(id),
    name             text NOT NULL,
    timezone         text NOT NULL,              -- IANA name, e.g. 'Europe/Berlin'
    opening_hours    jsonb NOT NULL,             -- per weekday {open,close}
    capacity_cap     int,                        -- FR-6.3; NULL = no cap
    check_in_enabled boolean NOT NULL DEFAULT true,   -- FR-4.7
    geofence_lat     double precision,
    geofence_lng     double precision,
    geofence_radius_m int NOT NULL DEFAULT 150
);

CREATE TABLE floor (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  uuid NOT NULL,
    site_id          uuid NOT NULL REFERENCES site(id),
    name             text NOT NULL,
    ordinal          int  NOT NULL,
    plan_asset_key   text,          -- object-store key, §9.2
    plan_width       int,           -- plan-space units, §9.1
    plan_height      int
);

CREATE TABLE zone (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  uuid NOT NULL,
    floor_id         uuid NOT NULL REFERENCES floor(id),
    name             text NOT NULL,
    polygon          jsonb NOT NULL,     -- [[x,y],...] in plan space
    restricted_to_group_id uuid REFERENCES user_group(id),   -- FR-6.4
    opens_to_all_at  time                                     -- FR-6.4 cut-off
);

-- The generalization the PRD's §6 asks for: desks, rooms, and later parking/lockers.
CREATE TABLE resource (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id   uuid NOT NULL,
    site_id           uuid NOT NULL REFERENCES site(id),
    floor_id          uuid REFERENCES floor(id),
    zone_id           uuid REFERENCES zone(id),
    kind              text NOT NULL CHECK (kind IN ('desk','room')),   -- extend, don't migrate
    name              text NOT NULL,
    capacity          int  NOT NULL DEFAULT 1,       -- rooms only
    attributes        jsonb NOT NULL DEFAULT '{}',   -- FR-2.5, FR-3.1
    status            text NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active','out_of_service','retired')),
    out_of_service_reason text,                      -- FR-8.6
    assigned_user_id  uuid REFERENCES app_user(id),  -- FR-6.7
    plan_x            real, plan_y real, plan_rotation real,   -- §9.1
    qr_key_version    int NOT NULL DEFAULT 1,        -- §8.1
    UNIQUE (organization_id, site_id, name)
);

CREATE INDEX resource_attrs_gin ON resource USING gin (attributes jsonb_path_ops);
```

Resource attributes are `jsonb` with a GIN index rather than an attribute table. FR-2.5's filter list
(sit/stand, monitors, dock, window, quiet, accessible) is open-ended and customer-specific; an EAV
table buys nothing here and costs a join on the hottest read path.

### 3.3 The booking table

```sql
CREATE TABLE booking (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  uuid NOT NULL,
    site_id          uuid NOT NULL REFERENCES site(id),   -- denormalized, see §3.4
    resource_id      uuid NOT NULL REFERENCES resource(id),
    user_id          uuid NOT NULL REFERENCES app_user(id),
    during           tstzrange NOT NULL,
    local_date       date NOT NULL,                       -- denormalized, see §3.4
    status           text NOT NULL
                     CHECK (status IN ('pending','confirmed','checked_in',
                                       'completed','cancelled','released_no_show')),
    created_by       uuid NOT NULL REFERENCES app_user(id),  -- FR-2.10 delegate recorded
    checked_in_at    timestamptz,
    released_at      timestamptz,
    cancellation_reason text,
    series_id        uuid,                                -- FR-2.7 recurrence grouping
    created_at       timestamptz NOT NULL DEFAULT now()
);
```

Indexes that matter:

```sql
CREATE INDEX booking_site_day    ON booking (site_id, local_date)
    WHERE status NOT IN ('cancelled','released_no_show');
CREATE INDEX booking_user_upcoming ON booking (user_id, local_date DESC);
CREATE INDEX booking_sweep       ON booking (status, local_date)
    WHERE status = 'confirmed';   -- §12.2 auto-release sweep
```

### 3.4 Timezones: one canonical rule (FR-2.14)

PRD §8.3 asks for a single canonical helper. Here it is, stated as a rule rather than a function:

> **A booking's day is the calendar date of its start instant in its site's timezone. The device's
> timezone is never consulted for anything except formatting a relative label like "in 2 hours".**

`booking.local_date` is computed once, at write time, as
`(lower(during) AT TIME ZONE site.timezone)::date`, and is never recomputed. `site_id` is
denormalized onto `booking` purely so this column can be derived and so day-scoped queries need no
join. Both denormalizations are justified by that single rule; neither is an optimization.

Consequences to hold onto:

- "Today" in the API is always resolved server-side from the site, never sent by the client.
- Policy windows (booking horizon, cancellation cut-off, check-in window) are evaluated in site time.
- A user with bookings at two sites in different timezones can legitimately have two "todays". The
  home screen groups by site for exactly this reason.
- Sites must not change timezone after bookings exist. The admin API rejects it; a genuine move is a
  new site.

### 3.5 Supporting tables

| Table | Purpose |
|---|---|
| `user_group`, `group_member` | Teams and arbitrary groups (PRD §6); policy and zone scoping |
| `role_grant(user_id, role, scope_type, scope_id)` | FR-1.8 — additive, site-scoped roles |
| `day_declaration(user_id, local_date, kind)` | FR-5.5 office/remote/leave; also feeds FR-5.4 team grid and FR-6.7 assigned-desk release |
| `policy(scope_type, scope_id, rule_key, value)` | FR-6.x, resolved by precedence in §4.3 |
| `site_day_capacity(site_id, local_date, booked_count, cap)` | FR-6.3 counter, §4.2 |
| `booking_attendee(booking_id, user_id \| email, response)` | FR-3.3 |
| `blackout(site_id \| floor_id, during, reason)` | FR-6.5 |
| `idempotency_key(...)` | §5.3 |
| `job(...)` | §12.1 |
| `device(user_id, platform, push_token)` | FR-7.1 |
| `refresh_token(user_id, family_id, hash, ...)` | §6.4 rotation and reuse detection |
| `audit_log(actor_id, action, target, before, after)` | FR-8.8 |
| `daily_utilization(...)` | §13 rollups |

`day_declaration` is worth noting: one small table satisfies three requirements that look unrelated
in the PRD. A user declaring "remote on Thursday" completes the team grid (FR-5.4), records their
non-attendance (FR-5.5), and releases their assigned desk to the pool for that date (FR-6.7).

---

## 4. Booking: allocation, capacity, policy

### 4.1 Double-booking is a schema property (FR-2.13)

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- needed for uuid equality inside a GiST index

ALTER TABLE booking ADD CONSTRAINT booking_no_double_allocation
    EXCLUDE USING gist (
        resource_id WITH =,
        during      WITH &&
    ) WHERE (status NOT IN ('cancelled','released_no_show'));
```

Two overlapping live bookings on one resource are not rejected by application code — they are
impossible to store. The partial predicate is what makes cancellation work: a cancelled booking stops
participating in the constraint and its slot reopens immediately, with no row deletion and no audit
loss.

`completed` deliberately *remains* in the constraint. A completed booking is history, but allowing a
new booking to overlap it would corrupt utilization data retroactively.

The application's job is reduced to translating the resulting error:

```python
try:
    await session.flush()
except IntegrityError as e:
    if e.orig.diag.constraint_name == "booking_no_double_allocation":
        raise ResourceTakenError(resource_id)   # → 409, §5.4
    raise
```

There is no `SELECT … FOR UPDATE` on the resource, no advisory lock, and no read-then-write race. The
Monday-morning spike (R6) resolves as ordinary Postgres write contention on a GiST index, which is
exactly the workload that index is built for. The losing request gets a 409 in single-digit
milliseconds.

**Amended 2026-09-19, from the Phase 0 skeleton.** The original draft of this section also claimed
"no optimistic retry loop". Building the §16.2 concurrency test disproved that. With many
simultaneous inserts against one resource, Postgres does **not** always produce a simple wait chain
on the exclusion constraint — with enough waiters it detects a deadlock (SQLSTATE `40P01`) and aborts
a transaction that would otherwise have *won* the race. At 12 concurrent attempts this was
reproducible.

Left unhandled, that surfaces to a user as "this desk was just taken" for a desk that is in fact
free, at precisely the Monday-morning moment when it is most visible. So the booking write is wrapped
in `with_booking_txn`, which owns the transaction and retries on `40P01` and `40001` up to three
times with a short backoff.

This is a bounded, SQLSTATE-specific retry, not a general optimistic-concurrency loop, and it does
not weaken the constraint — the constraint still decides who wins. But the original claim was too
strong, and the correction belongs here rather than in a commit message.

Two related details the skeleton also settled:

- **Range bounds are always explicit `[)`.** Relying on a library's default is a correctness bug
  waiting for a dependency upgrade: with inclusive bounds, 09:00–13:00 and 13:00–17:00 collide and
  half-day booking silently breaks.
- **The session dependency must roll back on exception.** A 409 leaves the transaction aborted, and
  anything reusing that session afterwards fails with `PendingRollbackError` instead of the real
  error.

**Test obligation:** §16.2 requires a concurrency test that fires N simultaneous requests at one
resource and asserts exactly one success. That test is the proof this design rests on.

### 4.2 Site capacity cap (FR-6.3)

The exclusion constraint prevents two people taking one desk; it says nothing about a site-wide cap
set *below* the physical desk count. That is a counting problem and needs a serialization point.

```sql
-- inside the booking transaction, only when site.capacity_cap IS NOT NULL
INSERT INTO site_day_capacity (organization_id, site_id, local_date, booked_count, cap)
VALUES (:org, :site, :date, 0, :cap)
ON CONFLICT (site_id, local_date) DO NOTHING;

SELECT booked_count, cap FROM site_day_capacity
WHERE site_id = :site AND local_date = :date FOR UPDATE;   -- serializes this (site, day)

-- if booked_count >= cap: raise CapacityExceeded → 409 with rule code
UPDATE site_day_capacity SET booked_count = booked_count + 1
WHERE site_id = :site AND local_date = :date;
```

The row lock is held for the remainder of a short transaction. Contention is per `(site, date)`, and
the Monday spike spreads across sites and across the days being booked, so this is acceptable — but
it *is* the one genuine serialization point in the booking path, and it is why the cap is optional.

**Sites without a cap skip this block entirely** and take the lock-free path. Most will. The counter
row doubles as the read model for the 7-day availability strip (FR-2.1), so it is not pure overhead.

Cancellation decrements in the same transaction as the status change. A nightly reconciliation job
(§12.2) recounts and corrects drift, because a counter that can silently diverge from the bookings it
counts is worth one cheap job to keep honest.

### 4.3 The policy engine and explainable refusals (FR-6.9)

Policies resolve by precedence: **group > site > organization**, most specific wins, evaluated per
`rule_key`. A rule is a small pure function:

```python
class Rule(Protocol):
    key: str
    def evaluate(self, ctx: PolicyContext) -> Denial | None: ...

@dataclass(frozen=True)
class Denial:
    code: str            # BOOKING_HORIZON_EXCEEDED
    message: str         # localized client-side from code + params
    rule_key: str
    scope: str           # "group:engineering"
    params: dict
```

`PolicyContext` is loaded once per request — user, groups, site, target resource, requested range,
the user's existing bookings, resolved policy values — and then all rules run against it as pure
functions with no further I/O. This makes the whole engine unit-testable without a database and makes
a dry run free (§5.2).

Rules at P0: booking horizon (FR-6.1), max concurrent future bookings (FR-6.2), site capacity
(FR-6.3), zone permission (FR-6.4), blackout (FR-6.5), opening hours, assigned-desk ownership
(FR-6.7), cancellation cut-off (FR-6.8).

**All rules are evaluated, not short-circuited.** The API returns every denial, because a UI that
fixes one refusal only to hit the next is the experience FR-6.9 exists to prevent. The client shows
the first and can reveal the rest.

Ordering is fixed and declared, so the "first" denial is deterministic: cheapest and most
comprehensible refusals first (blackout, opening hours), policy limits after.

### 4.4 Booking shapes, favourites, and proximity

**Slots (FR-2.2).** A booking is a `tstzrange`, so whole-day, morning, afternoon and custom ranges are
one write with different bounds. Named slots are derived from `site.opening_hours` — `day` is
open→close, `am` is open→midday, `pm` is midday→close — and resolved server-side, so a site opening at
07:00 gets sensible halves without the client hardcoding 09:00. The API accepts `slot` or an explicit
range, never both.

Half-days are also why the exclusion constraint ranges over time rather than keying on a date: two
people legitimately hold one desk on one day, and `&&` gets that right with no extra logic.

**Favourites (FR-2.8).** `favourite(user_id, resource_id | zone_id)`. "Book my usual" is a client
shortcut over existing endpoints — read the top favourite, `/bookings/validate`, book — so it costs
one table and no new API surface.

**Sit near a colleague (FR-5.3).** Because desks live in plan space (§9.1), "near" is Euclidean
distance on the floor. `GET /resources?near_user_id=&date=` resolves that colleague's booking for the
date and sorts free desks on the same floor by distance from it.

This endpoint is subject to the same privacy filter as §5.2, and the reason is worth stating: if a
colleague has hidden their presence under FR-5.6, asking to sit beside them must not reveal where
they are. A proximity search is a presence query wearing a different hat. The same ordering feeds
auto-assign (FR-2.9, P1).

---

## 5. API surface

### 5.1 Conventions

- REST over HTTPS, JSON only. FastAPI's generated OpenAPI schema is the contract; the TypeScript
  client is generated from it in CI and committed, so a drift between server and client is a failing
  build rather than a runtime bug (PRD §8.2).
- Errors are RFC 9457 `application/problem+json`, always carrying a machine `code`.
- Cursor pagination (`?cursor=&limit=`), never offset — booking lists change under the reader.
- `ETag` / `If-None-Match` on floor plans and resource lists; these are the large, rarely-changing
  reads that the mobile client fetches on every cold start.
- The tenant is derived from the access token, never from a request parameter. An endpoint that takes
  an `organization_id` from the client is a bug (§15.1).

### 5.2 Endpoint catalogue

**Auth** (§6)

```
POST   /auth/discover            {email} → {region, idp_kind, start_url}
GET    /auth/start               browser entry; 302 to IdP
GET    /auth/callback            IdP return; 302 to app deep link with one-time code
POST   /auth/token               {code} → {access_token, refresh_token}
POST   /auth/refresh             {refresh_token} → rotated pair
POST   /auth/magic-link          {email} → 202 (always)
POST   /auth/logout              revokes the refresh family
GET    /me                       profile, roles, home site, feature flags
```

**Browsing and availability**

```
GET    /sites                          user's permitted sites
GET    /sites/{id}/days?from=&to=      FR-2.1 seven-day strip: per-day free/total/mine
GET    /floors/{id}                    plan metadata + zones + resources (ETag'd)
GET    /floors/{id}/state?date=&slot=  per-resource booking state for one day (small, uncached)
GET    /resources?floor_id=&date=&slot=&attrs=…   FR-2.4 list view, relevance-sorted
```

The split between `/floors/{id}` (heavy, static, cacheable, offline-storable) and
`/floors/{id}/state` (small, volatile) is deliberate and is what lets the floor plan render instantly
from cache while availability streams in behind it (§11.2).

**Booking**

```
POST   /bookings              Idempotency-Key required → 201 | 409
POST   /bookings/validate     dry run: same policy evaluation, no write
POST   /bookings/batch        FR-2.6 multi-day; per-item results
GET    /bookings?scope=upcoming|day&…
PATCH  /bookings/{id}         modify time/resource — revalidated in full
DELETE /bookings/{id}         cancel (FR-2.12), subject to cut-off
```

`/bookings/validate` runs the identical `PolicyContext` and rule set as the write path and returns
the same `Denial` list. The client calls it to grey out illegal days in the date picker, so FR-6.9's
explanation appears *before* the user commits rather than as a rejection afterwards.

`/bookings/batch` returns **per-item results, not all-or-nothing**. "Tuesdays and Thursdays for the
next four weeks" (FR-2.6) with one full day should book the other seven, not fail entirely. The
response lists each requested day with `created | denied(code) | conflict`, and the client summarizes:
*"Booked 7 of 8 days. Thursday 9 Oct was full."*

**Check-in** (§8)

```
POST   /bookings/{id}/check-in   {method:'qr'|'geo', qr_token?, lat?, lng?}
POST   /bookings/{id}/check-out  FR-4.8
POST   /check-in/scan            {qr_token, lat?, lng?} — walk-up booking, FR-4.6
```

**People and presence**

```
GET    /people?site_id=&date=       FR-5.1 who's in, privacy-filtered server-side
GET    /people/{id}/schedule        FR-5.2, subject to FR-5.6
GET    /teams/{id}/week?start=      FR-5.4 grid
PUT    /me/declarations/{date}      FR-5.5 {kind: office|remote|leave}
PUT    /me/privacy                  FR-5.6
```

Privacy filtering happens in the query, not in the serializer. A user whose visibility is `nobody`
must not appear in the result set at all — filtering after the fact is how presence leaks into
`total` counts and debug logs.

**Admin** (FR-8.x)

```
POST   /sites | /floors | /zones            CRUD
POST   /floors/{id}/plan                    upload image/PDF → §9.2
POST   /resources/bulk                      FR-8.2 bulk placement + name templates
POST   /imports/resources | /imports/users  FR-8.3 CSV, dry-run then commit
GET|PUT /policies?scope=…                   FR-8.5, with affected-user preview
POST   /bookings/admin                      FR-8.6 book for anyone
POST   /resources/{id}/out-of-service       FR-8.6, with reason
POST   /qr/labels                           FR-8.7 → PDF label sheet
GET    /reports/utilization?…               §13
GET    /audit?…                             FR-8.8
```

CSV import is two-phase: `POST /imports/resources?dry_run=true` returns a per-row validation report,
and the admin commits the same file. Importing 400 desks and discovering row 287 was malformed
halfway through is the failure mode FR-8.3 must avoid.

### 5.3 Idempotency (PRD §8.3)

Every mutating booking endpoint requires an `Idempotency-Key` header. The client generates a UUID per
user intent — not per HTTP attempt — so a retry after a timeout carries the same key.

```sql
CREATE TABLE idempotency_key (
    organization_id uuid NOT NULL,
    key             text NOT NULL,
    request_hash    text NOT NULL,
    response_status int,
    response_body   jsonb,
    completed_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, key)
);
```

The row is inserted in the same transaction as the booking. A replay with a matching hash returns the
stored response; a replay with a *different* hash for the same key is a client bug and returns 422.
A key whose row exists but has no `completed_at` means a request is in flight: return 409
`REQUEST_IN_PROGRESS` and let the client retry shortly. Keys are purged after 24 hours.

This is what makes the offline check-in queue (§11.3) safe to drain blindly.

### 5.4 Error codes that the client must handle

| HTTP | `code` | Meaning |
|---|---|---|
| 409 | `RESOURCE_TAKEN` | Exclusion constraint fired — someone else won the race |
| 409 | `CAPACITY_EXCEEDED` | Site day cap reached (FR-6.3) |
| 409 | `POLICY_DENIED` | One or more rule denials; body carries the full list (FR-6.9) |
| 409 | `REQUEST_IN_PROGRESS` | Idempotent request still running |
| 410 | `BOOKING_RELEASED` | Auto-released before check-in (FR-4.4) |
| 422 | `IDEMPOTENCY_KEY_REUSED` | Same key, different payload |

A `POLICY_DENIED` body:

```json
{
  "type": "https://deskflow.app/errors/policy-denied",
  "title": "Booking refused",
  "status": 409,
  "code": "POLICY_DENIED",
  "denials": [
    { "code": "BOOKING_HORIZON_EXCEEDED", "rule_key": "booking_horizon_days",
      "scope": "group:engineering", "params": { "limit_days": 14 } }
  ]
}
```

Messages are localized on the client from `code` + `params` (FR-10.4). The server sends an English
fallback string but the client is not expected to display it.

---

## 6. Identity and access

### 6.1 Why a backend-for-frontend, not a public OIDC client

The client never speaks to the IdP directly. It opens a URL on our API in the system browser; our API
is the OIDC relying party; our API mints our own tokens.

This costs one redirect and buys three things: IdP client secrets stay server-side, the app has one
token format regardless of which IdP an org uses, and adding SAML later (FR-1.7) is a server-side
change with no app release. Against a small team, that is the right trade.

### 6.2 Sign-in flow (FR-1.1, FR-1.3)

```
1. User types work email.
2. App → POST /auth/discover {email}
        ← {region, idp_kind:'entra', start_url}
   Response is identical whether or not the user exists (§15.3).
3. App opens start_url in the SYSTEM BROWSER via @capacitor/browser.
   Never an embedded webview — Google and Microsoft both refuse it, and it
   defeats the SSO session the user already has.
4. API performs OIDC authorization-code + PKCE against the IdP.
5. IdP → GET /auth/callback. API validates, provisions or matches app_user,
   mints a ONE-TIME CODE (60s TTL, single use).
6. API 302s to the app's Universal Link / App Link:
        https://app.deskflow.example/auth/return?code=…
   which the OS routes into the app (@capacitor/app appUrlOpen).
   On web, the same route is handled in-page.
7. App → POST /auth/token {code} ← {access_token, refresh_token}
```

The one-time code exists so tokens never appear in a URL, browser history, or the OS's link-handling
logs. Universal Links are used rather than a custom `deskflow://` scheme because a custom scheme can
be claimed by any app on the device.

### 6.3 Token handling, native vs web

| | Native (Capacitor) | Web (admin console) |
|---|---|---|
| Access token | In memory, 10 min TTL | In memory, 10 min TTL |
| Refresh token | Keychain / Keystore via a secure-storage plugin | `httpOnly; Secure; SameSite=Lax` cookie |
| Transport | `Authorization: Bearer` | `Authorization: Bearer` |

Two transports for the refresh token, one for the access token. The split is unavoidable rather than
chosen: a pure-cookie design would be simpler, but the Capacitor webview runs on the
`capacitor://localhost` origin, so an API cookie is third-party and WKWebView's tracking prevention
will drop it. Bearer tokens on native and a cookie on web is the smallest correct answer, and it is
recorded here so nobody "simplifies" it back into a cookie and loses a week.

PRD §8.1.1 is explicit that `@capacitor/preferences` is **not** acceptable for the refresh token — it
is plaintext on disk.

### 6.4 Refresh rotation and revocation (FR-1.4)

Refresh tokens rotate on every use and are stored hashed, grouped into a *family* per sign-in.
Presenting a refresh token that has already been used means the token leaked: the entire family is
revoked immediately and the user re-authenticates. Admin session revoke (FR-1.4) revokes all families
for a user. Access tokens are short enough (10 min) that we do not maintain a denylist for them.

### 6.5 Magic link (FR-1.2)

Single-use signed token, 15-minute TTL, delivered by email, redeemed at `/auth/callback` and
converging on the same one-time-code handoff. Only permitted if the email's domain is allowlisted for
the org. `POST /auth/magic-link` always returns 202 regardless of whether the address exists, and is
rate-limited per address and per IP (§15.3).

### 6.6 Authorization (FR-1.8)

Roles are additive grants, each scoped: `role_grant(user_id, role, scope_type, scope_id)` where
`role ∈ {employee, team_lead, site_admin, org_admin}` and `scope_type ∈ {org, site, group}`.
Permission checks ask "does this user hold a role granting X over the scope containing this object",
which is a single indexed lookup against a scope chain resolved once per request and cached on the
request context.

**Deactivation (FR-8.4).** Deactivating a user cancels their future bookings in one transaction —
status `cancelled`, capacity counters decremented, audit rows written — and revokes every refresh
token family. Past bookings are retained until the retention purge (§13.2); deleting them would
falsify utilization history that has already been reported to a customer.

Delegated booking (FR-2.10) records both identities: `booking.user_id` is the beneficiary,
`booking.created_by` is the actor, and the audit log carries the pair.

---

## 7. Conference rooms

### 7.1 Rooms reuse the booking engine entirely

A room is `resource.kind = 'room'` with `capacity > 1` and richer `attributes` (display, VC,
whiteboard, phone, photos). It books through the same `POST /bookings`, the same policy engine, and
the same exclusion constraint that protects desks. There is no room booking service.

What is genuinely new for rooms is three pieces of UI and one table:

- **Day timeline** (FR-3.2) — a vertical time axis per room, fed by `/floors/{id}/state` widened to
  return ranges instead of a boolean. Same endpoint, richer projection.
- **Attendees** (FR-3.3) — `booking_attendee`, plus push to internal invitees and an accept/decline
  action. An accepted invitation surfaces on the attendee's home screen for that day without creating
  a booking for them; they are attending a meeting, not occupying a desk.
- **Find-a-room** (FR-3.5, P1) — "3 people, next 30 minutes, this floor" is a query over free ranges
  ordered by capacity fit, then a normal booking write.
- **Room check-in and auto-release** (FR-3.6/3.7, P1) — the desk sweep in §12.2 with a shorter window.

This is the payoff from Q3's revision: rooms cost a timeline view and an attendee list, not a
subsystem. PRD §11 is right that basic room booking could reasonably move into Phase 1.

### 7.2 No calendar integration, and the obligation that survives (FR-3.4)

There is **no Microsoft 365 or Google Calendar integration in either direction**. Rooms are bookable
only in this product. This removes the largest and highest-risk subsystem from the design — no
two-way sync, no delegated mailbox access, no free/busy reconciliation, no per-tenant admin consent,
no drift repair.

It leaves exactly one obligation, and it is organizational rather than technical:

> **If a room remains bookable as a resource mailbox in the customer's directory, it will eventually
> be booked in both systems, and we will not be able to detect it.**

We hold no free/busy data for that mailbox and have no signal that a conflicting booking exists. Two
groups arrive at one room; the product is blamed. There is no code that fixes this.

The mitigations are therefore procedural, and the design supports them:

1. **Directory lockdown is a hard onboarding gate.** Each room is marked
   `attributes.directory_locked_down` with the admin who attested and when. The admin console blocks
   publishing a floor containing rooms until every room is attested.
2. **Go-live checklist** records the attestation in the audit log, so the conversation after an
   incident is evidentiable.
3. **Adoption risk is validated early**, not designed around: Outlook-habituated employees are the
   real failure mode, and that is a design-partner question for week one (R1).

Deliberately *not* built: a "detect conflicting Outlook bookings" feature. It would require exactly
the calendar integration Q3 removed, and re-introducing it to police a policy problem would be the
worst of both designs.

### 7.3 Guests

External attendees (FR-3.3) are stored as bare email addresses on `booking_attendee`, receive an
email with an `.ics` attachment (FR-7.3), and have no account and no access. Visitor management is
explicitly out of scope (PRD §13); a guest here is an email string, nothing more.

---

## 8. Check-in

### 8.1 QR codes: what a signature can and cannot prove (FR-4.1)

The payload encoded in the printed label:

```
deskflow:v1:<resource_id>:<key_version>:<base64url HMAC-SHA256(resource_id|key_version, org_secret)>
```

The HMAC proves the label was generated by us. **It does not prove the person scanning it is present**
— a printed label is static, so a photograph of it is a perfect replica forever.

PRD §9.3 requires that a photographed code "must not be replayable indefinitely from home". That
requirement cannot be met by the code itself; it is met by the *context* in which a scan is accepted:

1. The scan must fall inside the check-in window for a booking the user holds on that resource
   (FR-4.3) — so a photo is useless except in a narrow window on a day you booked anyway.
2. **Where a site has a geofence configured, a QR check-in also requires a passing coarse location
   check.** This is the control that actually defeats checking in from home, and it means geofencing
   is not merely an alternative check-in method (FR-4.2) but a component of QR integrity.
3. `key_version` supports rotation: bumping an org's secret invalidates every existing label and
   FR-8.7 reprints them.

A site that disables check-in entirely (FR-4.7) or has no geofence accepts the QR alone. That is a
deliberate, documented weakening for customers whose works council rejects location checks — those
customers are trading data quality for acceptability, and they should know it.

### 8.2 Geofence check-in (FR-4.2) and what we store

A one-shot foreground position read via `@capacitor/geolocation` when the user opens check-in. The
client sends `lat`/`lng`; the server computes haversine distance against
`site.geofence_lat/lng/radius_m` and stores **only the boolean outcome** on the booking. Raw
coordinates are never written to a table, never logged, and exist only for the duration of the
request (PRD §9.4).

No PostGIS. One site geofence is a circle and haversine in Python is ten lines; adding a spatial
extension to compare a point against a radius would be infrastructure for its own sake.

No background location: the user is in the app when they check in, so there is nothing to observe in
the background. This also keeps the app's iOS location permission at "while in use", which is
materially easier to justify in a privacy review.

### 8.3 Walk-up booking (FR-4.6)

`POST /check-in/scan` with no existing booking: validate the HMAC, check the resource is free *now*,
run the full policy engine, create a booking already in `checked_in`, return it. One request, one
transaction, the same constraint. It is the check-in path and the booking path composed, not a third
path.

---

## 9. Floor plan: rendering and authoring

This is the long pole (PRD §11), delivers FR-2.3 and FR-8.2, and carries risk R8. It is also where the single-codebase decision
pays for itself: §9.3 and §9.4 describe one component in two modes, not two implementations.

### 9.1 Plan space

Desk coordinates are stored in **plan space** — an abstract coordinate system defined by
`floor.plan_width × plan_height`, not pixels of any particular image. Re-uploading a higher-resolution
plan, or swapping a PDF for a PNG, must not move 300 desks.

The client renders `<svg viewBox="0 0 plan_width plan_height">`, and every desk is a `<rect>` at
`(plan_x, plan_y)`. Zone polygons are arrays of plan-space points.

### 9.2 Plan ingestion (FR-8.1)

Upload accepts PNG, JPEG, or PDF. PDFs are rasterized server-side (first page, longest edge capped at
4096px) to WebP with a JPEG fallback; both are written to object storage and served through the CDN
with a content-hashed key and immutable caching. The original is retained so a higher-quality
re-render is possible later without asking the customer for the file again.

`plan_width`/`plan_height` are set from the rasterized dimensions on first upload and **frozen**.
Subsequent uploads are scaled to fit the existing plan space, which is what keeps desk positions
stable.

### 9.3 Rendering at 60fps in a webview (R8, PRD §9.1, PRD §8.1.2 condition 1)

The performance requirement is 300 desks, first render under 1.0s, sustained 60fps pan/zoom on
mid-tier Android. The naive React implementation — transform in state, re-render on pointer move —
will not achieve this. The design is specific:

**Structure.** One `<svg>`, rendered once. Inside it: an `<image>` background, a `<g>` of zone
polygons, a `<g>` of desk `<rect>`s. Roughly 350 nodes. Desk labels are rendered only above a zoom
threshold, because 300 `<text>` nodes cost more than the 300 rects they annotate.

**The gesture is not React's business.** Pointer events are handled on a wrapper `<div>`, accumulated
in a ref, and written straight to the DOM. No state, no re-render, no reconciliation, for the entire
duration of a drag or pinch.

**Two-phase transform — the part that matters.** There is a real trade-off in a webview:

- A `transform` attribute on an SVG `<g>` stays crisp but repaints the SVG subtree every frame.
- A CSS `transform` on an HTML wrapper is GPU-composited and cheap, but scales a rasterized layer, so
  it softens while the gesture is in flight.

We take both, in sequence:

```tsx
// DURING the gesture: composited CSS transform on the wrapper. Cheap, smooth, slightly soft.
function onPointerMove(e: PointerEvent) {
  t.current.x += e.movementX;
  t.current.y += e.movementY;
  wrapper.current!.style.transform =
    `translate3d(${t.current.x}px, ${t.current.y}px, 0) scale(${t.current.k})`;
}

// ON gesture end: fold the transform into the viewBox and reset the CSS transform.
// The SVG re-rasterizes once, at the new scale, crisp.
function onPointerUp() {
  const vb = viewBoxFrom(t.current);
  svg.current!.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  wrapper.current!.style.transform = '';
  t.current = { x: 0, y: 0, k: 1 };
  setViewBox(vb);          // the ONLY React state update in the whole interaction
}
```

The wrapper carries `will-change: transform` while a gesture is active and drops it afterwards, so
the compositor layer is not retained permanently.

**Desk state changes are attribute writes, not renders.** Availability arrives from
`/floors/{id}/state`; applying it sets `class` on the affected `<rect>`s directly. Colour lives in
CSS. A hundred desks changing state is a hundred `setAttribute` calls, not a React tree diff.

**Hit testing is native.** Each `<rect>` has a `data-resource-id` and a single delegated click
handler on the `<g>` reads it from `event.target`. No per-node React handlers, no hit-test maths.

This must be proven in Phase 0 on real low-end Android hardware with 300 nodes, before the rest of
the client depends on it (PRD §11).

### 9.4 The list alternative is not a fallback (FR-10.5)

The SVG is `aria-hidden="true"` and every floor-plan screen ships an equivalent list view reaching
the same actions with the same filters. The list is not a degraded mode: it is the accessible path,
it is often the *faster* path for a user who knows their desk, and FR-2.4 already requires it as a
first-class alternative. Anything bookable on the plan must be bookable in the list, and that
equivalence is an explicit test in §16.

### 9.5 The authoring mode (FR-8.2)

The admin editor is the same component with an `editable` prop. What it adds:

- **Bulk placement.** Drag a rectangle, specify rows × columns and a name template (`4F-A-01..24`);
  the client generates positions and names, and `POST /resources/bulk` writes them in one
  transaction. This is the answer to R5 — placing 300 desks one at a time is what stalls onboarding.
- **Drag to reposition**, snap-to-grid, multi-select, and attribute editing applied to a selection.
- **Zone drawing** — click to place polygon vertices.
- **A client-side undo stack.** Edits are local until saved; save is one batched request. An editor
  that writes on every drag is both slow and frightening to use.

The PRD is right that this is a small CAD-ish tool and deserves its own design review. Budget it as a
feature, not a form.

---

## 10. Client architecture

### 10.1 One application, two audiences

A single Vite + React + TypeScript app. Route-based code splitting puts the admin console behind a
lazily-loaded route tree, so the employee bundle stays small while the admin code ships in the same
artifact. Lazy chunks cost disk, not cold-start time (PRD §8.1).

```
src/
  api/          generated OpenAPI client — never hand-edited
  auth/         token store, refresh, deep-link return handling
  booking/      flows shared by app and console
  floorplan/    ONE component, viewer + editor modes (§9)
  offline/      query persistence, outbox (§11)
  native/       every Capacitor plugin call, behind an interface (§10.2)
  admin/        lazily loaded; console-only screens
  i18n/         en, de, fr, es (FR-10.4)
```

First-run onboarding (FR-1.9) — home site, team, default in-office days, notification permission —
writes through ordinary endpoints and is resumable: each step commits on its own, so an interrupted
sign-up resumes where it stopped rather than restarting. Notification permission is requested last,
after the user has seen why it matters, not on first launch.

Server state is TanStack Query throughout; there is no Redux-style global store. Booking data is
server data, and treating it as anything else creates two sources of truth about whether a desk is
free.

### 10.2 Native access goes through one layer

Every Capacitor plugin call lives behind an interface in `native/` with a web implementation
alongside it. Three reasons, in order of importance: the admin console runs in a browser with no
plugins; component tests run in jsdom; and swapping a plugin (likely at least once, given §17) is a
one-file change.

```ts
export interface Scanner { scan(): Promise<string>; }
// native/scanner.capacitor.ts → @capacitor-mlkit/barcode-scanning
// native/scanner.web.ts       → BarcodeDetector, or unsupported()
```

Camera scanning renders the native preview *behind* the webview, so the scanning screen sets the
webview transparent, draws its own reticle in HTML, and restores opacity on unmount — including on
the error path, because a webview left transparent is an app that looks broken (PRD §8.1.2,
condition 2).

### 10.3 Optimistic writes and honest rollback (FR-10.2)

Booking writes apply optimistically, then reconcile. When the server refuses, the UI does not simply
revert: it reverts *and states the reason*, using the `code` from §5.4. "That desk was taken a moment
ago" and "Engineering can only book 14 days ahead" are different messages, and FR-6.9 exists so the
user gets the right one.

---

## 11. Offline and sync

### 11.1 What works offline, and what deliberately does not

FR-10.1 requires today's and upcoming bookings, plus the QR scanner, to work with no connectivity,
with check-in queueing for later.

| Capability | Offline |
|---|---|
| View today's and upcoming bookings | Yes, from cache |
| View a cached floor plan | Yes |
| Scan a QR code | Yes, decoded on-device |
| Check in | **Queued**, syncs on reconnect |
| Declare remote/office day | Queued |
| **Create or modify a booking** | **No — and this is deliberate** |

Offline booking would require evaluating capacity caps, zone permissions and the exclusion constraint
against data the device cannot have. The honest options are to book optimistically and revoke later,
or to refuse. Revoking a desk someone believes they hold, hours after the fact, is worse than
refusing at the moment of intent. The app therefore shows a clear offline state on the booking path.

This is a constraint on FR-10.1 as written, surfaced here rather than discovered in Phase 1.

### 11.2 Read cache

TanStack Query with an IndexedDB persister. Cached across launches: profile and roles, bookings for
today ± 7 days, the user's sites, and floor metadata with resources. Floor plan images are cached by
the service worker under their content-hashed URL, so they are immutable and never revalidated.

The §5.2 split between `/floors/{id}` and `/floors/{id}/state` is what makes this work: the heavy,
stable part renders instantly from cache while live availability arrives behind it. A user opening
the app in a lift sees their floor, with desk states greyed until the network returns.

### 11.3 The outbox

Queued mutations are rows in IndexedDB:

```ts
interface OutboxEntry {
  id: string;            // UUID — ALSO the Idempotency-Key (§5.3)
  endpoint: string;
  body: unknown;
  createdAt: number;
  attempts: number;
}
```

The key property: the idempotency key is generated when the *user acts*, not when the request is
sent. A queued check-in retried across three reconnects and two app restarts carries one key
throughout, so the server treats attempts two and three as replays and returns the original response.
This is why §5.3 is a P0 dependency of offline support and not a nicety.

Drain is serial, oldest first, on reconnect and on app resume. A 4xx other than 409/`REQUEST_IN_PROGRESS`
is terminal: drop the entry and surface it. A 5xx or network failure retries with backoff. Entries
older than 24 hours are dropped with a notice — a check-in queued yesterday is not a fact about today.

**Server-authoritative conflict resolution.** There is no merge. The server's answer wins, and the
client explains it. For a check-in that arrives after auto-release, the server returns 410
`BOOKING_RELEASED` and the app says the desk was released and offers to rebook.

---

## 12. Background work and notifications

### 12.1 The job runner

PRD §8.2 reduced this from a broker to a table. The implementation:

```sql
CREATE TABLE job (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid,
    kind            text NOT NULL,
    payload         jsonb NOT NULL DEFAULT '{}',
    run_after       timestamptz NOT NULL DEFAULT now(),
    attempts        int NOT NULL DEFAULT 0,
    locked_at       timestamptz,
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','done','failed')),
    last_error      text
);
CREATE INDEX job_claimable ON job (run_after) WHERE status = 'pending';
```

```sql
UPDATE job SET status='running', locked_at=now(), attempts=attempts+1
WHERE id IN (
    SELECT id FROM job
    WHERE status='pending' AND run_after <= now()
    ORDER BY run_after
    FOR UPDATE SKIP LOCKED
    LIMIT 20
)
RETURNING *;
```

`SKIP LOCKED` makes multiple workers safe without coordination, so scaling out is adding a process.
Failures retry with exponential backoff up to five attempts, then land in `failed` and alert.
A job stuck in `running` past a timeout is reclaimed by a sweep — a crashed worker must not strand
work.

This is a few dozen lines against infrastructure we already operate. **The tripwire for revisiting
it:** sustained queue depth above a few thousand, or a p95 claim-to-start latency above a minute.
Until then, Redis and Celery would be two more things to run, monitor, secure and restore.

### 12.2 Scheduled sweeps

A single scheduler loop enqueues jobs. Every sweep is timezone-correct per site, using the §3.4 rule.

| Sweep | Cadence | Does |
|---|---|---|
| Check-in reminder | 5 min | Push at booking start (FR-4.5) |
| Auto-release warning | 5 min | Push before the deadline (FR-4.5) |
| **Auto-release** | 5 min | `confirmed` past its check-in deadline → `released_no_show`, decrement the capacity counter, notify (FR-4.4) |
| Evening-before reminder | hourly | 18:00 site-local for tomorrow's bookings (FR-7.1) |
| Completion | hourly | `checked_in` past its end → `completed` |
| Capacity reconciliation | nightly | Recount `site_day_capacity` against bookings (§4.2) |
| Utilization rollup | nightly | §13 |
| Retention purge | nightly | FR-9.7 |

Auto-release is the highest-consequence job in the system: it takes a desk away from someone. It runs
in one transaction per booking, is idempotent on status, skips sites with `check_in_enabled = false`
(FR-4.7), and writes an audit row every time. §16.4 requires the metric "released bookings per day
per site" to be alerted on — a bug here is silent and expensive.

### 12.3 Notification delivery (FR-7.1, FR-7.2, FR-7.4)

Push through APNs and FCM via `@capacitor/push-notifications`; email through a transactional provider
(§17). Both are enqueued as jobs, never sent inline in a request.

This is what satisfies PRD §9.2's degraded-mode requirement: **booking and check-in do not depend on
notification delivery.** A dead push provider backs up a queue; it does not fail a booking.

Preferences are per-channel and per-type (FR-7.4), enforced at enqueue. Quiet hours (FR-7.6) defer
rather than drop, computed in the user's site timezone. Every notification carries a deep link
(FR-10.3) resolving to the exact booking or floor.

---

## 13. Analytics and retention

### 13.1 Rollups, not live aggregation

The admin dashboard never queries `booking` directly. A nightly job writes:

```sql
CREATE TABLE daily_utilization (
    organization_id uuid NOT NULL,
    site_id  uuid NOT NULL,
    floor_id uuid,
    zone_id  uuid,
    date     date NOT NULL,
    capacity     int NOT NULL,
    booked       int NOT NULL,
    checked_in   int NOT NULL,
    no_shows     int NOT NULL,
    PRIMARY KEY (organization_id, site_id, floor_id, zone_id, date)
);
```

Peak-day and day-of-week patterns (FR-9.2) and no-show
rate over time (FR-9.3) are then ordinary queries over this table rather than scans of booking
history. This makes FR-9.1–9.3 trivially fast, keeps PRD §9.1's 200ms read budget safe as history grows, and —
the reason that matters most — makes retention possible: **rollups carry no personal data**, so
identifiable booking rows can be purged while the utilization history survives (FR-9.7).

The desk-level heat map (FR-9.4) needs per-resource counts; those roll up to
`resource_usage(resource_id, date, bookings, check_ins)`, which is also non-identifiable.

Today's numbers are computed live from the counters in §4.2 and merged over the rollups, so the
dashboard is current without scanning raw bookings.

### 13.2 Retention (FR-9.7)

Default 13 months for identifiable rows. The nightly purge deletes `booking`, `booking_attendee` and
`day_declaration` rows older than the org's configured retention, having confirmed the covering
rollup exists. Audit log retention is configured separately and longer, because it is a compliance
artifact.

### 13.2.1 The team week grid is forward-only (FR-5.4)

Added 2026-09-19, and it belongs in this section rather than under coordination.

`GET /teams/{id}/week` refuses a week that has already finished, returning 422 `PAST_WEEK`
with the earliest week it will serve. The client's "previous week" control stops at the
same boundary, so the refusal is a guard rail rather than an error someone hits.

This is a product position, not a missing feature. The grid shows *planned* presence so a
team can coordinate; the same grid scrolled backwards is a per-person attendance record,
which §13.3 and FR-9.5 rule out. The current week is allowed because it contains today —
the line is drawn at weeks that have ended, not at days that have passed.

A team lead who wants attendance history is asking for something this product deliberately
does not provide. If that requirement ever becomes real, it should arrive as an explicit,
separately-argued decision with its own privacy review, not as a quiet relaxation of the
date check.

### 13.3 The aggregation floor (FR-9.5)

Manager-facing team analytics are aggregated, never per-person. This is a product position, not a
default, so it is enforced in code rather than in the UI: the team-summary endpoint refuses to return
a breakdown for a group smaller than a configurable minimum (default 5) and returns
`GROUP_TOO_SMALL`. Without a floor, "aggregate" data about a team of two is a timesheet.

---

## 14. Infrastructure and environments

### 14.1 Runtime

| Piece | Choice | Note |
|---|---|---|
| API | FastAPI under Uvicorn workers, in a container | Stateless; scale horizontally |
| Worker | The same image, different entrypoint | One process at launch (§12.1) |
| Database | Managed Postgres 16, PITR enabled | The only stateful component |
| Object store | S3-compatible + CDN | Floor plans, QR label PDFs |
| Web hosting | The same built bundle, served static behind the CDN | Admin console + web app |

One image, two entrypoints. No platform-specific managed services on the critical path, which keeps
the EU deployment (§14.3) a configuration exercise rather than a port.

### 14.2 Environments

`dev` (per-engineer, Docker Compose), `staging` (production-shaped, anonymized seed data), `prod`.
Migrations run as a separate step before rollout and must be backward-compatible with the running
version — expand/contract, never a breaking ALTER in a deploy window.

PRD §9.2 sets RPO 5 min / RTO 1 hour: PITR covers the RPO, and the **quarterly restore test is a
scheduled calendar obligation**, not an aspiration. A backup nobody has restored is a hypothesis.

### 14.3 Regions and EU residency (PRD §9.4)

EU data residency is a Phase 4 commitment, but designing it out now would be expensive to undo. Two
rules protect it:

1. `organization.region` is authoritative, and `/auth/discover` returns the region so the client
   targets the right API host from the first call.
2. **No cross-region shared state.** Separate databases, separate object stores, no global tables. The
   only shared component is DNS.

This is a full stack per region, deliberately. Cross-region reads are the thing that makes residency
claims false.

### 14.5 Deployed on Vercel — what that costs

Deployed 2026-09-19. Two Vercel projects, one managed Postgres.

| Piece | Where |
|---|---|
| API | Vercel Python function, `api/index.py`, single ASGI entrypoint |
| Web | Vercel static build of the Vite bundle |
| Database | Prisma Postgres (`pooled.db.prisma.io`), Postgres 17 |

The client is cross-origin by construction (§6.3), so two projects is the natural shape
rather than a compromise: the web build carries `VITE_API_URL`, and the API allows exactly
the origins it is told about.

**Three things this hosting choice changes, and they are not small:**

1. **There is no worker.** §12.1 specifies a process that drains the job table; §12.2
   lists what it drains — check-in reminders, the auto-release sweep, completion, capacity
   reconciliation, rollups, retention purge. A serverless function cannot host any of it.
   Nothing regresses today because the worker was never built, but **auto-release (FR-4.4)
   cannot ship on this hosting without either Vercel Cron hitting an authenticated sweep
   endpoint, or a worker running somewhere else.** That decision belongs before Phase 2,
   not after.
2. **Connections go through a pooler**, so asyncpg runs with `statement_cache_size=0` and
   `ssl="require"` outside dev (`Settings.db_connect_args`). A transaction-mode pooler
   hands each transaction a different backend, and cached prepared statements then point
   at connections that no longer hold them — an intermittent failure under load, which is
   the worst kind to debug in production. The pool is deliberately small: the pooler does
   the real pooling, and a frozen function holding handles it will never reuse starves
   everyone else.
3. **Migrations do not run on deploy.** Alembic is excluded from the function bundle, so
   `alembic upgrade head` is run against the production URL from a machine that has it.
   That is fine at this size and wrong at a larger one; it should become a pipeline step
   before anyone else can deploy.

**The deployment runs on development sign-in, deliberately.** Real OIDC needs IdP
credentials (T6) and the magic-link fallback (FR-1.2) is unbuilt, so there was no way to
log in at all. Rather than leave it unusable, the deployment sets
`DESKFLOW_ALLOW_DEV_SIGN_IN=true`.

That decision is recorded here rather than left in a dashboard, because it is a real one:
`/auth/dev-sign-in` issues a valid token for any known email with no credential, so anyone
who can reach the API can sign in as anyone in it. It is acceptable while the database
holds invented demo data and unacceptable the moment it holds a real employee's name. The
API logs `dev_sign_in_exposed` at warning level on every cold start so this is visible in
the logs and not only in a config diff.

**The switch is deliberately separate from `environment`.** The obvious way to get this —
setting `DESKFLOW_ENVIRONMENT=dev` — would also drop `ssl="require"` and re-enable
asyncpg's statement cache (§14.5 item 2), breaking the managed pooler while granting far
more than intended. One switch, one effect, one name that says what it does.
`test_the_switch_does_not_relax_the_database_settings` asserts the separation, and the
default-off case is still asserted by
`test_dev_sign_in_does_not_exist_outside_dev_by_default` — an operator who forgets a
variable still gets the locked-down path.

### 14.4 Mobile build and release

GitHub Actions with a macOS runner plus fastlane; no managed equivalent to EAS Build exists here
(PRD §8.1.2, condition 6). Release builds on tag, TestFlight and Play internal track on merge to
main. The OTA question (§17) is open and affects only how JS-only fixes reach users, not this
pipeline.

---

## 15. Security and privacy implementation

### 15.1 Tenant isolation (PRD §9.3)

Every query goes through a repository layer that requires an `organization_id` sourced from the
access token. No handler constructs a query directly, and no endpoint accepts a tenant identifier
from the client. A resource fetched with a mismatched tenant returns **404, not 403** — a 403
confirms the object exists.

This is enforced by convention plus the test harness in §16.3, which is why that harness is a P0
deliverable and not a nice-to-have.

### 15.2 Why not row-level security yet

PRD §8.2 defers RLS to Phase 4. The reason, recorded so it is revisited deliberately: RLS requires a
per-transaction `SET LOCAL app.current_org`, and with async SQLAlchemy's connection pooling a
connection returned to the pool with a stale setting is a cross-tenant read — the exact failure RLS
was adopted to prevent. Done properly it needs disciplined session lifecycle management.

The §3.1 rule that *every* table carries `organization_id` is what keeps this cheap later: enabling
RLS becomes a migration plus a session-management change, not a schema redesign.

### 15.3 Abuse and enumeration

`/auth/discover` and `/auth/magic-link` both leak tenant membership if they answer honestly.
`/auth/discover` returns IdP routing for a *domain*, never confirmation that a user exists;
`/auth/magic-link` always returns 202. Both are rate-limited per address and per IP, as are check-in
scan attempts.

### 15.4 Configuration fails closed

Added 2026-09-19, from the Phase 0 skeleton.

Three behaviours are gated on `environment`: the JWT signing key, the database
credentials, and `/auth/dev-sign-in`, which mints a token for any user given nothing but
an email address. All are correct in dev and catastrophic in production, and all were
originally protected by a setting that *defaulted to dev*. An operator who forgot one
environment variable would have got a published signing key, a published database
password, and a live authentication bypass.

The rule is therefore inverted:

- **`environment` defaults to `prod`.** Running in dev is an explicit opt-in, which the
  Makefile, CI and the test fixtures each perform. An unconfigured deployment gets the
  locked-down path.
- **The process refuses to start** outside dev if the signing key is the one published in
  this repository, or is shorter than 32 characters. A guard that recognised only the exact
  default would be defeated by someone typing `changeme`.
- **The same applies to the database URL**, which is refused outside dev if it is the
  published default, has no password, uses the username as the password, uses a well-known
  placeholder, or has a password under 16 characters. This check is on *credentials, not
  topology*: a `localhost` database in production is legitimate — a socket, or a sidecar —
  so the guard must never drift into being a host allowlist.
- **`/auth/dev-sign-in` is mounted only in dev**, so elsewhere the route does not exist
  rather than existing and refusing. A later refactor can drop a refusal; it cannot
  accidentally re-register a router.

All of this is pinned by tests (`test_config_guard.py`, `test_dev_endpoint_isolation.py`),
the second of which starts real subprocesses and asserts a 404 in prod and staging. CI runs
a job whose only purpose is to confirm the guards still fire — **including a positive case**,
because a guard that rejects everything looks identical to a working one until the day it
blocks a deploy.

One constraint on every guard here: **an error message must never echo the value it
rejected.** These errors land in logs and crash reporters, so an error that helpfully prints
the password it refused has moved that password somewhere worse than the config file. There
is a test asserting this for both guards.

The general principle, worth applying to every setting added later: **a missing
configuration value must fail closed.** The cost of a noisy startup failure is minutes; the
cost of a silent insecure default is a breach.

### 15.5 Presence visibility

Built 2026-09-19 (FR-5.6, and the answer to PRD Q6).

`app/presence.py` is the only place the rule is expressed, and every endpoint that can
reveal where or when a named person is in the office goes through it:

| Setting | Who sees you |
|---|---|
| `everyone` | Anyone in the organization |
| `team` | Only people sharing a group with you |
| `nobody` | No one — but you still see yourself, and you can still book |

Above all three sits `organization.settings.presence_enabled`, the org-wide kill switch
that PRD §5.3 commits to for works-council sign-off. It is not a UI toggle; it is a
setting that makes every colleague view collapse to just the viewer.

Two implementation rules, both load-bearing:

- **The filter runs in the query, never the serializer.** A hidden colleague must be
  absent from the result set, not removed from it on the way out — filtering afterwards is
  how presence leaks into counts, pagination totals and debug logs.
- **A hidden colleague returns 404, not 403.** A 403 confirms the person exists and has
  hidden themselves, which is itself a disclosure. Same reasoning as §15.1.

`tests/test_presence_privacy.py` covers all three settings, the kill switch, the tenant
boundary, and the cases that are easy to get wrong: sharing *any* one group is enough;
hiding from colleagues must not hide your own desk from you; and changing the setting
takes effect on the next read rather than the next session. Removing the filter makes six
of those fail, which is how I know they are not vacuous.

**An obligation this creates.** The UI tells people that "Nobody" means they will not
appear in anyone's team view *or on the plan*. That is true today only because
`/floors/{id}/state` returns free/booked/mine and carries no identity. The moment the plan
shows who sits where — FR-5.7, initials, avatars, a sit-near marker — that endpoint must
filter through the same function, or the product will be lying in a sentence a works
council has read. The note is repeated at the top of `app/presence.py`, where someone
building FR-5.7 will actually be looking.

### 15.6 Data handled with care

- Raw coordinates are never stored or logged — only the geofence boolean (§8.2).
- `presence_visibility` is applied in the query, not the serializer (§5.2).
- No PII in application logs. Log user and org IDs; never emails, names, or coordinates.
- Secrets in a managed secret store; the QR HMAC key is per-org and rotatable (§8.1).
- TLS 1.3 in transit, encryption at rest, both platform-provided.

---

## 16. Testing strategy

Four test obligations carry disproportionate weight. Everything else is ordinary coverage.

### 16.1 Policy rules are pure, so test them exhaustively

Rules are pure functions over `PolicyContext` (§4.3). Every rule gets a table-driven unit test with no
database. This is the cheapest high-value testing in the system, and FR-6.9 means a wrong *message* is
a bug, not just a wrong outcome.

### 16.2 Concurrency

A test that fires N concurrent `POST /bookings` at one resource and asserts exactly one 201 and N-1
409s. This is the proof of §4.1. A variant does the same against a capped site to prove §4.2's counter
never exceeds its cap. Both run in CI, not just at review time — this is precisely the property that
a well-meaning refactor breaks silently.

### 16.3 Cross-tenant harness

A parameterized test that walks every route in the OpenAPI schema, authenticates as org A, and
attempts to act on org B's objects, asserting 404. Driving it from the schema means a new endpoint is
covered the day it is added — which is the only way this stays true (PRD §9.3).

### 16.4 Load and device

- **Monday-spike load test (R6):** the real shape — a burst at 08:00 local, not uniform RPS.
- **Floor plan on device (R8):** 300 nodes, real low-end Android, frame timings recorded. In Phase 0
  as a gate, then periodically, because this regresses quietly.
- **Accessibility equivalence:** an automated check that every resource actionable on the plan is
  actionable in the list view (§9.4).

Alerting mirrors these: booking 409 rate, auto-releases per site per day, job queue depth and failure
rate, and the booking funnel from PRD §8.3 — which must exist from Phase 1, since G1 and G3 cannot be
measured retroactively.

---

## 17. Decisions log and open questions

### 17.1 Decisions this document makes

| # | Decision | Rationale |
|---|---|---|
| D1 | Exclusion constraint, not application locking | §4.1 — correctness by schema; removes a bug class |
| D13 | Bounded retry on `40P01`/`40001` around the booking write | §4.1 — Phase 0 found real deadlocks among exclusion-constraint waiters |
| D14 | `tstzrange` bounds always written explicitly as `[)` | §4.1 — a library default here would silently break half-day booking |
| D15 | `environment` defaults to `prod`; dev is an explicit opt-in | §15.4 — a forgotten variable must not yield a live auth bypass |
| D16 | Dev-only routes are mounted conditionally, not gated inside the handler | §15.4 — a refactor can drop a check; it cannot re-register a router |
| D17 | Database credentials guarded on strength, not on host | §15.4 — a localhost database in prod is legitimate; a `deskflow:deskflow` one is not |
| D18 | Guard errors never echo the value they rejected | §15.4 — these messages reach logs and crash reporters |
| D19 | One presence-visibility function, applied in the query | §15.5 — a serializer-level filter leaks into counts and logs |
| D20 | A hidden colleague is 404, not 403 | §15.5 — 403 confirms they exist and have hidden themselves |
| D21 | The team week grid is forward-only | §13.2.1 — a backwards grid is an attendance record, not a coordination tool |
| D22 | Team member counts include only visible members | §15.5 — counting hidden people lets a viewer infer that someone is hidden |
| D23 | Migrations create only the tables of their own revision | §14.5 — `create_all()` reads today's models, so a migration stops being a snapshot |
| D24 | asyncpg runs without a statement cache outside dev | §14.5 — a transaction-mode pooler invalidates prepared statements |
| D25 | Dev sign-in has its own switch, not `environment=dev` | §14.5 — the blunt flip also breaks TLS and the pooler, and grants more than intended |
| D2 | `site_id` + `local_date` denormalized onto `booking` | §3.4 — serves the single timezone rule |
| D3 | `jsonb` attributes + GIN, not an EAV table | §3.2 — open-ended filters, no join on the hot path |
| D4 | Backend-for-frontend OIDC | §6.1 — secrets server-side, one token format, SAML later is server-only |
| D5 | Bearer on native, cookie on web | §6.3 — forced by WKWebView third-party cookie handling |
| D6 | Per-item results for batch booking | §5.2 — partial success is the useful outcome |
| D7 | No offline booking | §11.1 — refusing beats revoking hours later |
| D8 | Postgres job table, no broker | §12.1 — with a stated tripwire |
| D9 | Nightly rollups for all analytics | §13.1 — also what makes retention possible |
| D10 | Haversine, no PostGIS | §8.2 — one circle per site |
| D11 | Two-phase floor-plan transform | §9.3 — smooth during gesture, crisp after |
| D12 | Aggregation floor on team analytics | §13.3 — enforced in code, because it is a product position |

### 17.2 Open

| # | Question | Blocks | Owner |
|---|---|---|---|
| T1 | **OTA / live updates** — fund Capgo or self-host, or demote FR-10.7 to P2 | Release process; carried from PRD §8.1.2 condition 4 | Closes in Phase 0 |
| T2 | Transactional email provider | FR-7.2, and the EU residency story in §14.3 | Phase 0 |
| T3 | Container host | §14.1 — the design is deliberately portable, but one must be picked | Phase 0 |
| T4 | Does the design partner set a site capacity cap below desk count? | Whether §4.2's counter is on the common path or a rarity | Design partner, week one |
| T6 | Google Workspace / Entra client credentials | The `/auth/start` → `/auth/callback` leg; the skeleton stands in a dev provider for it. **Now blocking: the Vercel deployment cannot be signed into without it (§14.5)** | Phase 0 |
| T7 | Where does the background worker run? | FR-4.4 auto-release and every sweep in §12.2. Vercel Cron against an authenticated endpoint, or a worker host | Before Phase 2 |
| T5 | Recurrence model for FR-2.7 (P1) — materialize bookings up front, or expand lazily? | Phase 3 | Deferred |

### 17.3 Known limitations, stated rather than hidden

1. **A printed QR code cannot prove presence** (§8.1). Sites without a geofence accept a photographed
   code within the check-in window. This weakens FR-4.1 for check-in-disabled and geofence-free
   sites, by their own choice.
2. **A room left bookable in the customer's directory will be double-booked and we will not detect
   it** (§7.2). There is no technical mitigation, only an onboarding gate.
3. **Offline booking is not supported** (§11.1), which constrains FR-10.1 as written.
4. **The site capacity cap is a serialization point** (§4.2) and the one place the Monday spike can
   queue.
5. **PRD §9.1's sub-2.0s cold start is tight in a webview.** The runtime starts before our code does.
   Achievable with a small initial bundle and lazy admin routes, but it is the NFR most likely to need
   re-baselining after the Phase 0 spikes — and it should be re-baselined openly rather than quietly
   missed.
