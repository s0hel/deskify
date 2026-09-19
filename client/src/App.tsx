import { Suspense, lazy, useMemo, useState } from "react";

import { DeskList } from "./floorplan/DeskList";
import { FloorPlan, type Desk, type DeskState } from "./floorplan/FloorPlan";

// The admin console is lazily loaded so it never sits in the employee
// cold-start path (TDD §10.1).
const AdminConsole = lazy(() => import("./admin/AdminConsole"));

function demoDesks(n: number): Desk[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `desk-${i}`,
    name: `4F-A-${String(i + 1).padStart(3, "0")}`,
    plan_x: 60 + (i % 20) * 70,
    plan_y: 70 + Math.floor(i / 20) * 70,
    kind: "desk" as const,
  }));
}

export default function App() {
  const [view, setView] = useState<"plan" | "list" | "admin">("plan");
  const desks = useMemo(() => demoDesks(300), []);
  const states = useMemo<Record<string, DeskState>>(
    () =>
      Object.fromEntries(
        desks.map((d, i) => [d.id, (i % 7 === 0 ? "booked" : "free") as DeskState]),
      ),
    [desks],
  );

  return (
    <main>
      <nav>
        <button onClick={() => setView("plan")}>Plan</button>
        <button onClick={() => setView("list")}>List</button>
        <button onClick={() => setView("admin")}>Admin</button>
      </nav>
      {view === "plan" && (
        <FloorPlan planWidth={1600} planHeight={1000} desks={desks} states={states} />
      )}
      {view === "list" && <DeskList desks={desks} states={states} />}
      {view === "admin" && (
        <Suspense fallback={<p>Loading console…</p>}>
          <AdminConsole />
        </Suspense>
      )}
    </main>
  );
}
