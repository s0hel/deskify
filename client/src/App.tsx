import { Suspense, lazy, useEffect, useMemo, useState } from "react";

import { ApiError } from "./api/client";
import {
  useCancelBooking,
  useCreateBooking,
  useFloor,
  useFloorState,
  useFloors,
  useMyBookings,
  useSites,
} from "./api/hooks";
import { explain } from "./api/messages";
import { type Me, signIn } from "./auth/session";
import { nextDays, weekdayLabel } from "./booking/dates";
import { DeskList } from "./floorplan/DeskList";
import { FloorPlan, type Desk, type DeskState } from "./floorplan/FloorPlan";

const AdminConsole = lazy(() => import("./admin/AdminConsole"));

const DEMO_EMAIL = "priya@northwind.example";

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [view, setView] = useState<"plan" | "list" | "admin">("plan");
  const [notice, setNotice] = useState<string | null>(null);

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
  const floors = useFloors(site?.id);
  const floorId = floors.data?.[0]?.id;
  const floor = useFloor(floorId);

  const days = useMemo(
    () => (site ? nextDays(site.timezone, 7) : []),
    [site],
  );
  const [day, setDay] = useState<string | null>(null);
  const on = day ?? days[0] ?? "";

  const state = useFloorState(floorId, on);
  const myBookings = useMyBookings(signedIn);
  const book = useCreateBooking();
  const cancel = useCancelBooking();

  // The API returns plan-space coordinates; anything unplaced cannot be drawn.
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

  const states = (state.data?.states ?? {}) as Record<string, DeskState>;

  function onSelect(resourceId: string) {
    if (!floorId || !on) return;
    setNotice(null);

    if (states[resourceId] === "mine") {
      const mine = myBookings.data?.find(
        (b) => b.resource_id === resourceId && b.local_date === on,
      );
      if (mine) {
        cancel.mutate(
          { bookingId: mine.id, on, floorId },
          { onSuccess: () => setNotice("Booking cancelled.") },
        );
      }
      return;
    }

    book.mutate(
      { resourceId, on, floorId },
      {
        onSuccess: () => {
          setNotice(null);
          myBookings.refetch();
        },
        // The rollback happens in the hook; this is the "and say why" half.
        onError: (err) =>
          setNotice(
            err.denials?.length
              ? explain(err.denials[0])
              : explain({ code: err.code, rule_key: "", scope: "", params: {} }),
          ),
      },
    );
  }

  if (authError) {
    return (
      <main className="shell">
        <p className="notice notice--error">{authError}</p>
      </main>
    );
  }

  if (!signedIn || sites.isLoading || floor.isLoading) {
    return (
      <main className="shell">
        <p className="muted">Signing in and loading the floor…</p>
      </main>
    );
  }

  const booked = Object.values(states).filter((s) => s === "booked" || s === "mine").length;
  const free = Object.values(states).filter((s) => s === "free").length;

  return (
    <main className="shell">
      <header className="bar">
        <div>
          <strong>{site?.name}</strong>
          <span className="muted"> · {site?.timezone}</span>
        </div>
        <div className="muted">{me?.display_name}</div>
      </header>

      <nav className="days" aria-label="Choose a day">
        {days.map((d) => (
          <button
            key={d}
            type="button"
            className={d === on ? "day day--on" : "day"}
            aria-pressed={d === on}
            onClick={() => {
              setDay(d);
              setNotice(null);
            }}
          >
            {weekdayLabel(d)}
          </button>
        ))}
      </nav>

      <div className="bar">
        <div className="tabs">
          <button onClick={() => setView("plan")} aria-pressed={view === "plan"}>
            Plan
          </button>
          <button onClick={() => setView("list")} aria-pressed={view === "list"}>
            List
          </button>
          <button onClick={() => setView("admin")} aria-pressed={view === "admin"}>
            Admin
          </button>
        </div>
        <div className="muted">
          {state.isFetching ? "updating…" : `${free} free · ${booked} booked`}
        </div>
      </div>

      {notice && <p className="notice">{notice}</p>}

      {view === "plan" && floor.data && (
        <FloorPlan
          planWidth={floor.data.plan_width ?? 1600}
          planHeight={floor.data.plan_height ?? 1000}
          desks={desks}
          states={states}
          onSelect={onSelect}
        />
      )}
      {view === "list" && <DeskList desks={desks} states={states} onSelect={onSelect} />}
      {view === "admin" && (
        <Suspense fallback={<p className="muted">Loading console…</p>}>
          <AdminConsole />
        </Suspense>
      )}
    </main>
  );
}
