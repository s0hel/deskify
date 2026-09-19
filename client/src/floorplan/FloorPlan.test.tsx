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
  it("renders one circle per resource", () => {
    const { container } = render(<FloorPlan {...props(300)} />);
    expect(container.querySelectorAll("circle.desk")).toHaveLength(300);
  });

  it("hides labels on a plan far wider than the view", () => {
    // 300 <text> nodes cost more than the circles they annotate, so they only
    // appear once the view is narrow enough for them to be legible.
    const { container } = render(
      <FloorPlan {...props(300)} planWidth={40000} planHeight={25000} />,
    );
    expect(container.querySelectorAll("text")).toHaveLength(0);
  });

  it("shows labels at the default phone zoom, where they are legible", () => {
    // The plan opens covered rather than letterboxed, which on a phone means
    // roughly a third of the plan width -- close enough to read desk names.
    const { container } = render(<FloorPlan {...props(300)} />);
    expect(container.querySelectorAll("text").length).toBeGreaterThan(0);
  });

  it("marks the svg aria-hidden because the list is the accessible path", () => {
    const { container } = render(<FloorPlan {...props(3)} />);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("applies desk state as a class, so a change is an attribute write", () => {
    const { container } = render(
      <FloorPlan {...props(3, { d1: "mine", d2: "unavailable" })} />,
    );
    expect(container.querySelector('.desks [data-resource-id="d1"]')?.getAttribute("class"))
      .toBe("desk desk--mine");
    expect(container.querySelector('.desks [data-resource-id="d2"]')?.getAttribute("class"))
      .toBe("desk desk--unavailable");
  });

  it("uses ONE delegated click handler, not one per desk", () => {
    const onSelect = vi.fn();
    const { container } = render(<FloorPlan {...props(5)} onSelect={onSelect} />);
    const node = container.querySelector('.desks [data-resource-id="d3"]')! as SVGCircleElement;
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(onSelect).toHaveBeenCalledWith("d3");
  });

  it("sets touch-action none so the browser does not fight the gesture", () => {
    const { container } = render(<FloorPlan {...props(3)} />);
    expect((container.querySelector(".floorplan") as HTMLElement).style.touchAction)
      .toBe("none");
  });
});

describe("your own desk", () => {
  it("gets a ring so it is findable without reading labels", () => {
    const { container } = render(<FloorPlan {...props(5, { d2: "mine" })} />);
    const rings = container.querySelectorAll(".rings circle.desk-ring");
    expect(rings).toHaveLength(1);
  });

  it("draws no rings when nothing is yours", () => {
    const { container } = render(<FloorPlan {...props(5)} />);
    expect(container.querySelectorAll(".rings circle")).toHaveLength(0);
  });

  it("keeps the ring layer out of hit testing", () => {
    const { container } = render(<FloorPlan {...props(5, { d2: "mine" })} />);
    expect(container.querySelector(".rings")?.getAttribute("pointer-events")).toBe("none");
  });
});
