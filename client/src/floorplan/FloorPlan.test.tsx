/**
 * Behavioural guards on the rules in FloorPlan.tsx. These exist because the
 * rules are easy to break in a refactor that "looks cleaner" and the cost only
 * shows up on a real device (risk R8).
 */

import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FloorPlan, type Desk, type DeskState } from "./FloorPlan";

function desks(n: number): Desk[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `d${i}`,
    name: `4F-A-${i}`,
    plan_x: i * 10,
    plan_y: 0,
    kind: "desk" as const,
  }));
}

const props = (n: number, states: Record<string, DeskState> = {}) => ({
  planWidth: 1600,
  planHeight: 1000,
  desks: desks(n),
  states,
});

describe("FloorPlan", () => {
  it("renders one rect per resource", () => {
    const { container } = render(<FloorPlan {...props(300)} />);
    expect(container.querySelectorAll("rect.desk")).toHaveLength(300);
  });

  it("keeps the node count low by hiding labels when zoomed out", () => {
    const { container } = render(<FloorPlan {...props(300)} />);
    // 300 rects, no <text>: labels cost more than the rects they annotate.
    expect(container.querySelectorAll("text")).toHaveLength(0);
  });

  it("marks the svg aria-hidden because the list is the accessible path", () => {
    const { container } = render(<FloorPlan {...props(3)} />);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("applies desk state as a class, so a change is an attribute write", () => {
    const { container } = render(
      <FloorPlan {...props(3, { d1: "mine", d2: "unavailable" })} />,
    );
    expect(container.querySelector('[data-resource-id="d1"]')?.getAttribute("class"))
      .toBe("desk desk--mine");
    expect(container.querySelector('[data-resource-id="d2"]')?.getAttribute("class"))
      .toBe("desk desk--unavailable");
  });

  it("uses ONE delegated click handler, not one per desk", () => {
    const onSelect = vi.fn();
    const { container } = render(<FloorPlan {...props(5)} onSelect={onSelect} />);
    const rect = container.querySelector('[data-resource-id="d3"]')! as SVGRectElement;
    rect.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(onSelect).toHaveBeenCalledWith("d3");
  });

  it("sets touch-action none so the browser does not fight the gesture", () => {
    const { container } = render(<FloorPlan {...props(3)} />);
    expect((container.querySelector(".floorplan") as HTMLElement).style.touchAction)
      .toBe("none");
  });
});
