/**
 * The accessible path (FR-10.5, TDD §9.4).
 *
 * This is NOT a degraded mode. Anything bookable on the plan must be bookable
 * here, and §16.4 tests that equivalence. It is also often the faster path for
 * someone who already knows which desk they want.
 */

import type { Desk, DeskState } from "./FloorPlan";

const LABEL: Record<DeskState, string> = {
  free: "Available",
  booked: "Booked by someone else",
  mine: "Your booking",
  unavailable: "Out of service",
  assigned: "Assigned to another person",
};

export function DeskList({
  desks,
  states,
  onSelect,
}: {
  desks: Desk[];
  states: Record<string, DeskState>;
  onSelect?: (id: string) => void;
}) {
  return (
    <ul className="desk-list" aria-label="Desks on this floor">
      {desks.map((d) => {
        const state = states[d.id] ?? "free";
        const bookable = state === "free";
        return (
          <li key={d.id}>
            <button
              type="button"
              data-resource-id={d.id}
              disabled={!bookable}
              onClick={() => onSelect?.(d.id)}
              aria-label={`${d.name}. ${LABEL[state]}`}
            >
              <span>{d.name}</span>
              <span className={`state state--${state}`}>{LABEL[state]}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
