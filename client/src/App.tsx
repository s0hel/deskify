import { Suspense, lazy, useEffect, useMemo, useState } from "react";

import { ApiError } from "./api/client";
import {
  useCancelBooking,
  useCreateBooking,
  useDays,
  useFloor,
  useFloorState,
  useFloors,
  useSites,
  type ApiResource,
} from "./api/hooks";
import { type Me, signIn } from "./auth/session";
import { DeskSheet } from "./booking/DeskSheet";
import { RefusalSheet, type Refusal } from "./booking/RefusalSheet";
import { TodayCard, NextInOffice } from "./booking/TodayCard";
import { WeekStrip } from "./booking/WeekStrip";
import { dayName, displayDate, longLabel, siteToday, weekdayLabel } from "./booking/dates";
import { DeskList } from "./floorplan/DeskList";
import { FloorPlan, type Desk, type DeskState } from "./floorplan/FloorPlan";
import { initials } from "./ui/bits";

const AdminConsole = lazy(() => import("./admin/AdminConsole"));

const DEMO_EMAIL = "priya@northwind.example";
type Screen = "today" | "plan" | "admin";

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [screen, setScreen] = useState<Screen>("today");
  const [mode, setMode] = useState<"plan" | "list">("plan");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  useEffect(() => {
    signIn(DEMO_EMAIL)
      .then(setMe)
      .catch((e) =>
        setAuthError(
          e instanceof ApiError
            ? `Sign-in failed (${e.code}). Is the API running on :8099?`
            : "Could not reach the API. Is it running on :8099?",
        ),
      );
  }, []);

  const signedIn = me !== null;
  const sites = useSites(signedIn);
  const site = sites.data?.[0];
  const days = useDays(site?.id);
  const floors = useFloors(site?.id);
  const floorId = floors.data?.[0]?.id;
  const floor = useFloor(floorId);

  const todayIso = site ? siteToday(site.timezone) : "";
  const [day, setDay] = useState<string | null>(null);
  const on = day ?? todayIso;

  const state = useFloorState(floorId, on);
  const book = useCreateBooking();
  const cancel = useCancelBooking();

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

  if (!signedIn || sites.isLoading || days.isLoading) {
    return (
      <main className="app safe">
        <div className="pad" style={{ paddingTop: 40 }}>
          <p className="meta">Signing in…</p>
        </div>
      </main>
    );
  }

  const selected = selectedId ? (byId.get(selectedId) ?? null) : null;

  return (
    <main className="app safe">
      <header className="topbar">
        <div>
          <span className="eyebrow">
            {weekdayLabel(on).split(" ")[0]} · {site?.name}
          </span>
          {screen === "today" ? (
            <h1 className="display">{displayDate(on)}</h1>
          ) : (
            <h1 className="title" style={{ marginTop: 2 }}>
              {floor.data?.name ?? "Floor"}
            </h1>
          )}
        </div>
        <div className="avatar" aria-hidden="true">
          {initials(me?.display_name ?? "")}
        </div>
      </header>

      {screen === "today" && (
        <div className="scroll">
          <div className="pad" style={{ marginTop: 14 }}>
            <TodayCard
              day={dayRecord}
              dayLabel={on === todayIso ? "Today" : longLabel(on)}
              siteName={site?.name ?? ""}
              onShowPlan={() => setScreen("plan")}
              onFindDesk={() => setScreen("plan")}
            />
          </div>

          <section className="section">
            <span className="eyebrow pad" style={{ display: "block", marginBottom: 10 }}>
              Your week
            </span>
            <WeekStrip days={week} selected={on} todayIso={todayIso} onPick={pickDay} />
          </section>

          <NextInOffice days={days.data ?? []} labelFor={longLabel} onPick={pickDay} />

          <div className="pad section">
            <button className="btn btn--quiet" onClick={() => setScreen("admin")}>
              Admin console
            </button>
          </div>
          <div style={{ height: 32 }} />
        </div>
      )}

      {screen === "plan" && (
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
            <button className="pill" onClick={() => setScreen("today")}>
              {weekdayLabel(on)}
            </button>
          </div>

          {mode === "plan" && floor.data ? (
            <FloorPlan
              planWidth={floor.data.plan_width ?? 1600}
              planHeight={floor.data.plan_height ?? 1000}
              desks={desks}
              states={states}
              onSelect={setSelectedId}
            />
          ) : (
            <div className="scroll pad" style={{ paddingTop: 108 }}>
              <DeskList desks={desks} states={states} onSelect={setSelectedId} />
              <div style={{ height: 32 }} />
            </div>
          )}
        </div>
      )}

      {screen === "admin" && (
        <div className="scroll pad">
          <Suspense fallback={<p className="meta">Loading console…</p>}>
            <AdminConsole />
          </Suspense>
          <button className="btn btn--quiet" style={{ marginTop: 16 }} onClick={() => setScreen("today")}>
            Back
          </button>
        </div>
      )}

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
