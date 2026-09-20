# deskify — Phase 0 skeleton

Flex workspace booking. See [docs/PRD.md](docs/PRD.md) and
[docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md).

**Stack:** React + Capacitor · FastAPI + Postgres.

---

## Quick start

```bash
make seed     # Postgres + migrations + a demo tenant: 6 offices, 8 floors, 752 desks
make plans    # redraw the floor-plan SVGs from their one definition
make api      # API  -> http://localhost:8099  (/docs for OpenAPI)
make web      # app  -> http://localhost:5173
make test     # the full suite, both halves
```

The app signs in as `priya@northwind.example` automatically in dev, opens on **her
default office** — Tampa, of the six the seed creates — and books against the real
API. Tapping a free desk books it; tapping your own booking cancels it. Both the plan
and the list do this.

Tests run against a **separate** `deskify_test` database, created and migrated on first
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
| Team, colleague and profile screens; presence privacy (FR-5.1/5.2/5.5/5.6) | Done |
| Default office per user, and a home screen built on it (FR-1.9 home site, FR-2.1) | Done |
| Team week grid with anchor days (FR-5.4) | Done |
| Generated TypeScript client | Done — `client/src/api/schema.d.ts` |
| OIDC end to end for one IdP | **Blocked on IdP credentials** (T6) |
| 300-desk floor-plan spike on device | **Harness ready, gate not yet run on hardware** |
| iOS platform, native arm64 simulator build | Done — `client/ios` |
| Barcode scanning | Plugin settled (PRD §8.1.2 cond. 2); **scan not run — needs a camera** |
| OTA decision | **Open** (T1) |

The three unfinished rows are the ones that need a Mac with Xcode, an Android
device, and an IdP tenant. Everything that can be verified on a laptop is
verified and running.

---

## Deployed

| | | Vercel root directory |
|---|---|---|
| Web | https://deskify-web-eight.vercel.app | `client` |
| API | https://deskify-api-pi.vercel.app | `api` |
| Database | Prisma Postgres, migrated to head | |

```bash
curl https://deskify-api-pi.vercel.app/health
```

**Both projects deploy from a subdirectory, and that is a project setting, not
something this repository can state.** Vercel reads `vercel.json` *from* the root
directory, so `client/vercel.json` and `api/vercel.json` are only read when the
setting is right — and when it is wrong the failure does not mention it. `deskify-web`
spent its first day building at the repository root, where there is no `package.json`,
and reported `ENOENT ... /vercel/path0/package.json` on every push while serving a
months-stale build from its last good deployment. Check this first if a deploy fails
in a way that makes no sense:

```bash
vercel project inspect deskify-web        # Root Directory should read: client
vercel project update deskify-web --root-directory client --yes
```

**Sign-in on this deployment is the development one.** Real OIDC needs Google or Entra
credentials (T6) and the magic-link fallback is unbuilt, so the deployment runs with
`DESKIFY_ALLOW_DEV_SIGN_IN=true`: `/auth/dev-sign-in` issues a valid token for any seeded
email with no credential. That is a deliberate choice for a demo carrying invented data,
and it is one variable to unset before real names go in.

Use the dedicated switch, never `DESKIFY_ENVIRONMENT=dev`. The environment also selects
the database connection options — dev drops `ssl="require"` and re-enables asyncpg's
statement cache, which breaks the managed pooler. The narrow switch does one thing, and
`test_the_switch_does_not_relax_the_database_settings` holds that line.

**There is also no background worker**, so the auto-release sweep (FR-4.4) and the other
scheduled jobs have nowhere to run. See TDD §14.5 and open question T7.

Migrations are run by hand against the production URL:

```bash
cd api && env $(grep -v '^#' .env.prod | xargs) uv run alembic upgrade head
```

## Configuration fails closed

`DESKIFY_ENVIRONMENT` defaults to **`prod`**, not dev. Three things depend on it — the
JWT signing key, the database credentials, and `/auth/dev-sign-in`, which mints a token
for any user from an email alone. A forgotten variable must not hand out a published
signing key, a published database password, and a live auth bypass, so dev is an
explicit opt-in:

- the `make` targets export `DESKIFY_ENVIRONMENT=dev`
- CI sets it for the test jobs
- `tests/conftest.py` sets it before anything imports `app.config`

Outside dev the API **refuses to start** if:

| Setting | Refused when |
|---|---|
| `DESKIFY_JWT_SECRET` | it is the default in this repo, or under 32 characters |
| `DESKIFY_DATABASE_URL` | it is the default in this repo, has no password, uses the username as the password, uses a placeholder (`changeme`, `postgres`, …), or the password is under 16 characters |

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

Three patterns are worth knowing before changing anything:

- **The plan opens covered, not letterboxed.** `coverViewBox` gives the viewBox the
  *container's* aspect ratio, so the plan fills a tall phone screen and is panned, rather
  than sitting in a strip with dead space beneath it. Label visibility is judged by
  rendered pixel size, not a fraction of the plan.
- **The home screen names the building.** `WelcomeHero` says which office you are
  looking at, because everything under it is scoped to one, and a screen that stays
  silent about that is quietly wrong the week you are somewhere else. Its illustration
  is inline SVG in the token palette, and its lit windows are a hash of the site id —
  so two offices look different and one office always looks the same.
- **A refusal offers a way forward.** `RefusalSheet` names the problem in plain language,
  then lists the nearest days that actually have space and lets you jump to one. FR-6.9
  asks the app to say which rule refused a booking; a refusal that only explains is still
  a dead end. The machine code sits in small type at the bottom, addressed to support
  rather than to the person reading it.

## Your default office

A user has a **home site** (`app_user.home_site_id`), and everything the home screen
shows — the welcome, the availability, the week strip, the floor plan — is scoped to
it. `PUT /me/home-site` sets it; the app reaches that from two places, the hero on the
home screen and the Me screen, through one `HomeSiteSheet` so the two cannot drift.

Two decisions worth knowing:

- **`GET /me` resolves which office to open on, the client does not.** It returns
  `home_site_id` — NULL until the user chooses, per FR-1.9 onboarding — *and*
  `home_site`, the site to actually show: the chosen one, or the org's first by name.
  The client used to take `sites[0]`, which meant the API and the app each had an
  opinion about which office you were looking at. The fallback is sorted by name so it
  is the same office on every request, and a `home_site_id` pointing at a site that has
  since gone falls back rather than opening the app on nothing.
- **A home site is a default, not a fence.** You can book at any site in your org, and
  the seed shows it: Ren is homed at London Bridge and has desks in Tampa this week.
  Sign in as `dana@` or `kofi@` instead and the app opens on Berlin or Singapore.
  The hero's line changes from "Change your office" to "Is this your usual office?"
  when the office on screen is the fallback rather than the user's answer.

`PUT /me/home-site` takes the site id in the **body**, so the schema-driven
cross-tenant harness — which substitutes victim ids into *paths* — cannot reach it.
That case is asserted by hand in `tests/test_home_site.py`, and the path is listed in
the harness's `NO_OBJECT_ID` with that reason.

## Floor plans: one definition, two outputs

A floor plan exists twice — as desk coordinates in the database, and as a drawing
behind them — and the two have to agree to the pixel or the desks sit in the corridor.
So they are not authored twice. `api/app/floorplans.py` is the single definition;
`app/seed.py` reads the desks out of it and `app/plans.py` renders the drawing to
`client/public/plans/<key>.svg`, which `floor.plan_asset_key` names.

```bash
make plans                              # redraw
cd api && uv run python -m app.plans --check   # what CI runs
```

The SVGs are committed, so a clean checkout builds without running Python, and drift
fails the build the same way a stale generated API client does.

Six offices and eight floors across five archetypes, because one rectangle of evenly
spaced dots tells you nothing about whether the plan component copes:

| Office | Floor | Layout | Desks |
|---|---|---|---|
| Tampa | 4F | open banks of benching, rooms and core down one side | 300 |
| | 5F | central spine, benching either side | 96 |
| Berlin Mitte | 2F | central spine | 96 |
| | 3F | loft | 40 |
| Singapore Raffles | 12F | **L-shaped plate** — two outline rects, not one | 72 |
| London Bridge | 1F | courtyard around a **void**, rooms east and west | 60 |
| Austin Domain | 1F | loft: mostly not desks | 48 |
| Denver Union | 3F | loft, smaller | 40 |

Tampa keeps the 300, so `make seed` still opens the app on the PRD §9.1 budget rather
than on a toy.

Three things are worth knowing before changing a layout:

- **Nothing places a desk by hand.** `bench()` returns the seats *and* the rect they
  sit on, from one calculation, so the furniture cannot drift from the seating.
- **The invariants are tested, not eyeballed.** `tests/test_floorplans.py` asserts
  every desk is on the floorplate, none is in an atrium, none overlaps another or a
  bookable room's circle, and the committed SVG matches the generator. Each of those
  has already caught something — desks off the end of the L-shaped wing, and a plate
  sized for twice the benching that was placed in it.
- **The drawing is loaded with `<image>`, so it is an isolated document.** No CSS from
  the app reaches it, which is deliberate: the plan renders once and pan/zoom never
  touches React (FloorPlan.tsx rule 1), and inlining would add a few hundred nodes to
  that tree for nothing. The cost is that the theme has to come from inside, so the
  generated stylesheet carries its own `prefers-color-scheme` block. The app's manual
  `data-theme="light"` override cannot reach it.

## Picking a floor

`GET /sites/{id}/floors?on=` carries **free and total per floor**, not just names,
because nobody opens a floor picker to admire the naming scheme — they open it to
find out which floor has space. Computing it server-side is also what stops the
client firing one `/state` call per floor to colour a list.

Three decisions in the client are worth knowing:

- **The selected floor is derived, not held in an effect.** It is the picked id *if
  the current site still has it*, otherwise the lowest floor. Change office and the
  picked id is simply no longer in the new list, so it falls back on its own — an
  effect that reset it would have to race the query that replaced the list.
- **The heading is the control.** On the plan screen the title already says which
  floor you are on, so that is where you change it. On a single-floor site it renders
  as plain text with no disclosure arrow: an affordance for a choice that does not
  exist is worse than none.
- **"Sit near" carries the floor.** It always received one and always ignored it,
  which was invisible while every site had exactly one floor and would have quietly
  opened the wrong storey the day one did not.

## Office photographs

`client/src/assets/offices/<slug>.jpg` — `Berlin Mitte` becomes `berlin-mitte.jpg`.
`siteSlug` in `client/src/booking/photos.ts` and `slugify` in `api/app/floorplans.py`
are the same rule from opposite ends, tested against one list of cases.

They are resolved with a glob, not named imports, so **a missing photo is not a build
error** — the welcome hero falls back to its drawn illustration, which is what most
tenants will actually see. Verified by building with the directory emptied.

`*.jpg` there is **gitignored**. The images this was built against are iStock comps:
watermarked, unlicensed previews. Committing them would put someone else's marked-up
property in the repository and ship a watermark across the middle of the first screen
anyone sees. Drop licensed files in with these names and they appear.

## Presence privacy

Three settings — everyone, my teams only, nobody — plus an org-wide kill switch in
`organization.settings.presence_enabled`. The rule lives in exactly one function,
`app/presence.py`, and is applied **in the query**: a hidden colleague is absent from the
result, not stripped from it afterwards. A colleague you cannot see returns 404 rather
than 403, because 403 would confirm they exist and have hidden themselves.

The seed sets this up so it is visible in the demo, not just in tests: Dana is
`team`-only in Design, and Jo is `nobody`. Sign in as Priya (Engineering) and neither
appears on the Team screen.

The team week grid inherits all of it, and adds one rule: **member counts include only
people you can see**. Counting a hidden teammate would let you infer that someone is
hidden, which is the same disclosure by arithmetic.

The grid is also **forward-only** — `GET /teams/{id}/week` refuses a finished week with
422 `PAST_WEEK`. That is a product position (TDD §13.2.1): a grid you can scroll backwards
through is a per-person attendance record, which FR-9.5 rules out.

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
- **`test_presence_privacy.py`** — all three visibility settings, the org kill switch, and
  the tenant boundary. Deleting the filter makes six of them fail.
- **`test_home_site.py`** — the fallback, the choice, the stale pointer, and the
  body-parameter cross-tenant case the path-driven harness cannot see.
- **`test_floorplans.py`** — the layout invariants above, one per floor. Geometry is
  the kind of thing that looks fine in a screenshot and is wrong by 40 pixels.
- **`test_team_week.py`** — the grid's privacy inheritance (no row *and* no count for a
  hidden teammate) and the forward-only boundary.

---

## iOS

```bash
make ios                                              # local API
make ios IOS_API_URL=https://deskify-api-pi.vercel.app # deployed API
```

`client/ios/` is **committed**, deliberately. It is where `Info.plist` lives, and that file
carries `NSCameraUsageDescription` and `NSLocationWhenInUseUsageDescription` — without them
iOS kills the app instead of showing a permission prompt. Treating the directory as a build
artifact means regenerating it silently deletes those strings.

**The API address is compiled into the bundle.** There is no `server.url` in
`capacitor.config.ts` (see the comment there) and no runtime config, so `VITE_API_URL` must be
set at build time; a production build with none throws at startup rather than quietly calling
the phone itself. Cleartext `http://localhost` is fine on a **simulator** — it shares the host
network and iOS exempts loopback from App Transport Security — but a real device has neither,
so builds for hardware need an `https://` URL.

### QR scanning uses `@capacitor/barcode-scanner`, not ML Kit

The original pick, `@capacitor-mlkit/barcode-scanning`, was dropped in Phase 0 (PRD §8.1.2
condition 2). It drew the camera preview *behind* the webview, so the app had to turn its own
background transparent and restore it on every exit path including the throwing one — a P0 flow
one missed `finally` away from an invisible app.

The deciding constraint was architectural: GoogleMLKit ships fat `.framework` binaries whose
arm64 slice is the **device** slice, so its podspec sets
`EXCLUDED_ARCHS[sdk=iphonesimulator*] = arm64`. Every release through 9.0.0 does this, so there
is no version to upgrade to, and on Apple Silicon it means no native simulator build of this app.
`OSBarcodeLib`, under the replacement, ships an xcframework with an `ios-arm64_x86_64-simulator`
slice.

Before adding any native dependency, check that one line:

```bash
pod spec cat <PodName> --version=<v> | grep EXCLUDED_ARCHS
```

**The scan itself is still unverified** — a simulator has no camera, and nothing calls `scan()`
yet (FR-4.1 is unbuilt). What is verified is that the app builds native arm64, launches, and
loads live data.

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
    floorplans.py       the ONE floor-layout definition
    plans.py            renders it to client/public/plans/*.svg
    booking_service.py  the write path (TDD §4)
    policy.py           pure rules (TDD §4.3)
    repository.py       tenancy (TDD §15.1)
    timezone.py         the ONE day-boundary rule (TDD §3.4)
    routers/
  tests/
client/
  src/
    floorplan/          ONE component, viewer + editor (TDD §9)
    assets/offices/     one photo per site, gitignored, optional
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
