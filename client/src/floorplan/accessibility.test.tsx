/**
 * TDD §16.4 -- the accessibility equivalence test.
 *
 * "Anything bookable on the plan must be bookable in the list." The list is the
 * accessible path, not a fallback (FR-10.5), so this equivalence is an
 * automated check rather than a convention.
 */

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DeskList } from "./DeskList";
import { FloorPlan, type Desk, type DeskState } from "./FloorPlan";

const desks: Desk[] = Array.from({ length: 40 }, (_, i) => ({
  id: `d${i}`,
  name: `4F-A-${i}`,
  plan_x: i * 10,
  plan_y: 0,
  kind: i % 10 === 0 ? ("room" as const) : ("desk" as const),
}));

const states: Record<string, DeskState> = Object.fromEntries(
  desks.map((d, i) => [
    d.id,
    (["free", "booked", "mine", "unavailable", "assigned"] as DeskState[])[i % 5],
  ]),
);

function idsIn(container: HTMLElement, selector: string): Set<string> {
  return new Set(
    [...container.querySelectorAll(selector)].map(
      (n) => n.getAttribute("data-resource-id")!,
    ),
  );
}

describe("plan and list equivalence", () => {
  it("every resource on the plan appears in the list", () => {
    const plan = render(
      <FloorPlan planWidth={1600} planHeight={1000} desks={desks} states={states} />,
    );
    const list = render(<DeskList desks={desks} states={states} />);

    expect(idsIn(list.container, "button[data-resource-id]")).toEqual(
      idsIn(plan.container, "rect[data-resource-id]"),
    );
  });

  it("every desk bookable on the plan is bookable in the list", () => {
    const list = render(<DeskList desks={desks} states={states} />);
    const bookableOnPlan = desks.filter((d) => states[d.id] === "free").map((d) => d.id);

    for (const id of bookableOnPlan) {
      const btn = list.container.querySelector<HTMLButtonElement>(
        `button[data-resource-id="${id}"]`,
      );
      expect(btn, `${id} missing from the list`).toBeTruthy();
      expect(btn!.disabled, `${id} bookable on the plan but disabled in the list`).toBe(
        false,
      );
    }
    expect(bookableOnPlan.length).toBeGreaterThan(0);
  });

  it("gives every control a screen-reader label carrying its state", () => {
    const list = render(<DeskList desks={desks} states={states} />);
    for (const btn of list.container.querySelectorAll("button")) {
      expect(btn.getAttribute("aria-label")).toMatch(/4F-A-\d+\. \w/);
    }
  });
});
