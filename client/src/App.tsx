import { useEffect, useMemo, useState } from "react";

import { ApiError } from "./api/client";
import {
  useCancelBooking,
  useCreateBooking,
  useDays,
  useFloor,
  useFloorState,
  useFloors,
  useMe,
  useSetDeclaration,
  type ApiResource,
} from "./api/hooks";
import { type Me, signIn, signOut } from "./auth/session";
import { AbsenceSheet } from "./booking/AbsenceSheet";
import { DeskSheet } from "./booking/DeskSheet";
import { RefusalSheet, type Refusal } from "./booking/RefusalSheet";
import { TodayCard, NextInOffice } from "./booking/TodayCard";
import { WeekStrip } from "./booking/WeekStrip";
import { WelcomeHero } from "./booking/WelcomeHero";
import { planUrl } from "./booking/photos";
import { dayName, longLabel, siteToday, weekdayLabel } from "./booking/dates";
import { DeskList } from "./floorplan/DeskList";
import { FloorPlan, type Desk, type DeskState } from "./floorplan/FloorPlan";
import { FloorSheet } from "./floorplan/FloorSheet";
import { HomeSiteSheet } from "./people/HomeSiteSheet";
import { MeScreen } from "./people/MeScreen";
import { PersonScreen } from "./people/PersonScreen";
import { TeamScreen } from "./people/TeamScreen";
import { TabBar, type Tab } from "./ui/TabBar";
import { initials } from "./ui/bits";

const DEMO_EMAIL = "priya@northwind.example";

/**
 * Sign-in fails for three quite different reasons, and saying "is it running on
 * :8099?" to someone looking at a deployed URL is worse than saying nothing.
 *
 * The 404 case is the one that matters: outside dev the API deliberately does
 * not mount /auth/dev-sign-in, and real OIDC needs IdP credentials this build
 * does not have (TDD §17.2, T6). That is a deployment being incomplete, not a
 * fault to debug.
 */
function describeSignInFailure(error: unknown): string {
  const local = import.meta.env.DEV;

  if (error instanceof ApiError) {
    if (error.status === 404) {
      return local
        ? "Development sign-in is switched off. Is DESKIFY_ENVIRONMENT=dev set on the API?"
        : "This deployment has no sign-in configured yet. It needs an identity provider (Google Workspace or Microsoft Entra) before anyone can sign in.";
    }
    return `Sign-in failed (${error.code}).`;
  }

  return local
    ? "Could not reach the API. Is it running on :8099?"
    : "Could not reach the API.";
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("today");
  const [mode, setMode] = useState<"plan" | "list">("plan");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [personId, setPersonId] = useState<string | null>(null);
  const [focusResourceId, setFocusResourceId] = useState<string | null>(null);
  const [absenceOpen, setAbsenceOpen] = useState(false);
  const [officeOpen, setOfficeOpen] = useState(false);
  const [floorOpen, setFloorOpen] = useState(false);
  const [pickedFloorId, setPickedFloorId] = useState<string | null>(null);

  useEffect(() => {
    signIn(DEMO_EMAIL)
      .then(setMe)
      .catch((e) => setAuthError(describeSignInFailure(e)));
  }, []);

  const signedIn = me !== null;
  // Which office we are showing is a PROFILE fact, not "whichever site came
  // back first" (FR-1.9, FR-2.1). The API resolves it -- including the
  // fallback for someone who has never chosen -- so there is one answer.
  const profile = useMe(signedIn);
  const site = profile.data?.home_site ?? undefined;
  const days = useDays(site?.id);

  const todayIso = site ? siteToday(site.timezone) : "";
  const [day, setDay] = useState<string | null>(null);
  const on = day ?? todayIso;

  const floors = useFloors(site?.id, on);
  /**
   * The picked floor, or the lowest one. Derived rather than held in an
   * effect: when the office changes, the picked id is simply no longer in
   * the new site's list, so this falls back on its own. An effect that reset
   * it would have to race the query that replaced the list.
   */
  const floorId =
    pickedFloorId && floors.data?.some((f) => f.id === pickedFloorId)
      ? pickedFloorId
      : floors.data?.[0]?.id;
  const floor = useFloor(floorId);
  const manyFloors = (floors.data?.length ?? 0) > 1;

  const state = useFloorState(floorId, on);
  const book = useCreateBooking();
  const cancel = useCancelBooking();
  const declare = useSetDeclaration();

  const week = useMemo(() => (days.data ?? []).slice(0, 7), [days.data]);
  const dayRecord = days.data?.find((d) => d.date === on);

  const desks: Desk[] = useMemo(
    () =>
      (floor.data?.resources ?? [])
        .filter((r) => r.plan_x !== null && r.plan_y !== null)
        .map((r) => ({
          id: r.id,
          name: r.name,
          plan_x: r.plan_x as number,
          plan_y: r.plan_y as number,
          kind: r.kind,
        })),
    [floor.data],
  );
  const byId = useMemo(() => {
    const m = new Map<string, ApiResource>();
    for (const r of floor.data?.resources ?? []) m.set(r.id, r);
    return m;
  }, [floor.data]);

  const states = (state.data?.states ?? {}) as Record<string, DeskState>;
  const free = Object.values(states).filter((s) => s === "free").length;

  /** Days after the attempted one that actually have room (FR-6.9's way forward). */
  const alternatives = useMemo(
    () =>
      (days.data ?? [])
        .filter((d) => d.date !== refusal?.attempted && d.free > 0)
        .slice(0, 3),
    [days.data, refusal],
  );

  function pickDay(iso: string) {
    setDay(iso);
    setRefusal(null);
  }

  function openPerson(userId: string) {
    setPersonId(userId);
  }

  /** From a colleague's schedule: go to the plan for that day, centred on
   *  their desk. The disclosure is the same one their schedule already made.
   *
   *  The floor matters now that a site can have several. Without this the
   *  plan would open on the lowest floor and silently fail to find a desk
   *  that is two storeys up. */
  function sitNear(dayIso: string, resourceId: string, theirFloorId: string) {
    setDay(dayIso);
    setPickedFloorId(theirFloorId);
    setFocusResourceId(resourceId);
    setPersonId(null);
    setMode("plan");
    setTab("spaces");
  }

  function act(resourceId: string) {
    const current = states[resourceId];
    if (!floorId) return;

    if (current === "mine") {
      const bookingId = dayRecord?.my_booking_id;
      if (bookingId) {
        cancel.mutate({ bookingId, on, floorId }, { onSuccess: () => setSelectedId(null) });
      }
      return;
    }

    book.mutate(
      { resourceId, on, floorId },
      {
        onSuccess: () => setSelectedId(null),
        onError: (err) => {
          setSelectedId(null);
          setRefusal({ code: err.code, denial: err.denials?.[0] ?? null, attempted: on });
        },
      },
    );
  }

  if (authError) {
    return (
      <main className="app safe">
        <div className="pad" style={{ paddingTop: 40 }}>
          <div className="card">
            <span className="eyebrow eyebrow--clay">Not connected</span>
            <p className="body" style={{ marginTop: 8 }}>{authError}</p>
          </div>
        </div>
      </main>
    );
  }

  if (!signedIn || profile.isLoading || days.isLoading) {
    return (
      <main className="app safe">
        <div className="pad" style={{ paddingTop: 40 }}>
          <p className="meta">Signing in…</p>
        </div>
      </main>
    );
  }

  const selected = selectedId ? (byId.get(selectedId) ?? null) : null;
  // The today tab has no topbar heading -- the hero is its header -- so there
  // is no case for it here.
  const heading =
    tab === "spaces" ? (floor.data?.name ?? "Floor") : tab === "team" ? "Team" : "Me";

  return (
    <main className="app safe">
      <header className="topbar">
        <div>
          {personId ? (
            <button className="link-back" onClick={() => setPersonId(null)}>
              ‹ Back
            </button>
          ) : (
            // On the today tab the hero below IS the header -- it names the
            // office and the date -- so repeating either here is noise.
            tab !== "today" && (
              <>
                <span className="eyebrow">
                  {weekdayLabel(on).split(" ")[0]} · {site?.name}
                </span>
                {/* On the plan the heading IS the floor name, so it is also
                    where you change it -- but only when there is a choice.
                    A disclosure arrow on a one-floor site promises a
                    decision that does not exist. */}
                {tab === "spaces" && manyFloors ? (
                  <button className="heading-pick" onClick={() => setFloorOpen(true)}>
                    <h1 className="title">{heading}</h1>
                    <svg
                      width="18" height="18" viewBox="0 0 24 24" fill="none"
                      aria-hidden="true"
                    >
                      <path
                        d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2"
                        strokeLinecap="round" strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                ) : (
                  <h1 className="title" style={{ marginTop: 2 }}>
                    {heading}
                  </h1>
                )}
              </>
            )
          )}
        </div>
        {!personId && (
          <div className="avatar" aria-hidden="true">
            {initials(me?.display_name ?? "")}
          </div>
        )}
      </header>

      {personId ? (
        <PersonScreen
          userId={personId}
          todayIso={todayIso}
          onSitNear={sitNear}
          onBack={() => setPersonId(null)}
        />
      ) : (
        <>
          {tab === "today" && (
            <div className="scroll">
              {site && (
                <div className="pad" style={{ marginTop: 6 }}>
                  <WelcomeHero
                    siteId={site.id}
                    siteName={site.name}
                    name={profile.data?.display_name ?? me?.display_name ?? ""}
                    todayLabel={longLabel(todayIso)}
                    chosen={profile.data?.home_site_id !== null}
                    onChangeSite={() => setOfficeOpen(true)}
                  />
                </div>
              )}

              <div className="pad" style={{ marginTop: 14 }}>
                <TodayCard
                  day={dayRecord}
                  dayLabel={on === todayIso ? "Today" : longLabel(on)}
                  siteName={site?.name ?? ""}
                  onShowPlan={() => {
                    setFocusResourceId(null);
                    setTab("spaces");
                  }}
                />
              </div>

              {/* One primary action, always in the same place. It is hidden
                  only when there is genuinely nothing to book that day --
                  the week strip below is the way forward from there. */}
              {dayRecord && dayRecord.free > 0 && (
                <div className="pad" style={{ marginTop: 14 }}>
                  <button
                    className="btn btn--primary"
                    onClick={() => {
                      setFocusResourceId(null);
                      setTab("spaces");
                    }}
                  >
                    Book a space
                  </button>
                </div>
              )}

              <section className="section">
                <span className="eyebrow pad" style={{ display: "block", marginBottom: 10 }}>
                  Your week
                </span>
                <WeekStrip days={week} selected={on} todayIso={todayIso} onPick={pickDay} />
              </section>

              <div className="pad section">
                <button className="btn btn--quiet" onClick={() => setAbsenceOpen(true)}>
                  {dayRecord?.declaration
                    ? "Change what you're doing"
                    : "I'm not coming in"}
                </button>
              </div>

              <NextInOffice days={days.data ?? []} labelFor={longLabel} onPick={pickDay} />
              <div style={{ height: 24 }} />
            </div>
          )}

          {tab === "spaces" && (
            <div className="plan-screen">
              <div className="plan-controls">
                <div className="plan-controls__stack">
                  <div className="seg">
                    <button aria-pressed={mode === "plan"} onClick={() => setMode("plan")}>
                      Plan
                    </button>
                    <button aria-pressed={mode === "list"} onClick={() => setMode("list")}>
                      List
                    </button>
                  </div>
                  <span className="pill tabular">
                    <span className="count-free">{free} free</span>
                    <span className="count-total">of {desks.length}</span>
                  </span>
                </div>
                <button className="pill" onClick={() => setTab("today")}>
                  {weekdayLabel(on)}
                </button>
              </div>

              {mode === "plan" && floor.data ? (
                <FloorPlan
                  planWidth={floor.data.plan_width ?? 1600}
                  planHeight={floor.data.plan_height ?? 1000}
                  planImageUrl={planUrl(floor.data.plan_asset_key)}
                  desks={desks}
                  states={states}
                  onSelect={setSelectedId}
                  focusResourceId={focusResourceId}
                />
              ) : (
                <div className="scroll pad" style={{ paddingTop: 108 }}>
                  <DeskList desks={desks} states={states} onSelect={setSelectedId} />
                  <div style={{ height: 32 }} />
                </div>
              )}
            </div>
          )}

          {tab === "team" && (
            <TeamScreen
              days={week}
              selected={on}
              todayIso={todayIso}
              onPickDay={pickDay}
              onOpenPerson={openPerson}
            />
          )}

          {tab === "me" && (
            <MeScreen
              onSignOut={() => {
                signOut();
                setMe(null);
                setAuthError("Signed out. Reload to sign in again.");
              }}
            />
          )}
        </>
      )}

      {!personId && <TabBar active={tab} onChange={setTab} />}

      {selected && (
        <DeskSheet
          resource={selected}
          state={states[selected.id] ?? "free"}
          dayLabel={on === todayIso ? "today" : dayName(on)}
          busy={book.isPending || cancel.isPending}
          onBook={() => act(selected.id)}
          onCancel={() => act(selected.id)}
          onClose={() => setSelectedId(null)}
        />
      )}

      {absenceOpen && (
        <AbsenceSheet
          dayLabel={on === todayIso ? "Today" : longLabel(on)}
          current={dayRecord?.declaration ?? null}
          busy={declare.isPending}
          onChoose={(kind) =>
            declare.mutate({ on, kind }, { onSuccess: () => setAbsenceOpen(false) })
          }
          onClear={() =>
            declare.mutate({ on, kind: null }, { onSuccess: () => setAbsenceOpen(false) })
          }
          onClose={() => setAbsenceOpen(false)}
        />
      )}

      {floorOpen && floors.data && (
        <FloorSheet
          floors={floors.data}
          currentId={floorId}
          dayLabel={on === todayIso ? "today" : longLabel(on)}
          onPick={(id) => {
            setPickedFloorId(id);
            setFocusResourceId(null);
          }}
          onClose={() => setFloorOpen(false)}
        />
      )}

      {officeOpen && (
        <HomeSiteSheet
          currentSiteId={profile.data?.home_site?.id ?? null}
          onClose={() => setOfficeOpen(false)}
        />
      )}

      {refusal && (
        <RefusalSheet
          refusal={refusal}
          dayLabel={longLabel(refusal.attempted)}
          alternatives={alternatives}
          labelFor={longLabel}
          onPickDay={pickDay}
          onClose={() => setRefusal(null)}
        />
      )}
    </main>
  );
}
