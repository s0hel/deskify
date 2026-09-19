import { describe, expect, it } from "vitest";

import { clampViewBox, coverViewBox, foldTransform, shouldRenderLabels, toCss } from "./viewbox";

const PLAN = { w: 1600, h: 1000 };
const PHONE = { w: 375, h: 700 }; // tall and narrow: the hard case
const WIDE = { w: 1200, h: 600 };

describe("coverViewBox", () => {
  it("fills a tall phone screen rather than letterboxing the plan", () => {
    const vb = coverViewBox(PLAN, PHONE);
    // The view must be at least as tall as the plan, so no dead space shows.
    expect(vb.h).toBe(PLAN.h);
    expect(vb.w).toBeLessThan(PLAN.w);
  });

  it("gives the viewBox the CONTAINER's aspect ratio, not the plan's", () => {
    const vb = coverViewBox(PLAN, PHONE);
    expect(vb.w / vb.h).toBeCloseTo(PHONE.w / PHONE.h, 5);
  });

  it("centres the view on the plan", () => {
    const vb = coverViewBox(PLAN, PHONE);
    expect(vb.x + vb.w / 2).toBeCloseTo(PLAN.w / 2, 5);
    expect(vb.y + vb.h / 2).toBeCloseTo(PLAN.h / 2, 5);
  });

  it("shows the whole width on a container wider than the plan", () => {
    const vb = coverViewBox(PLAN, WIDE);
    expect(vb.w).toBe(PLAN.w);
    expect(vb.w / vb.h).toBeCloseTo(WIDE.w / WIDE.h, 5);
  });
});

describe("foldTransform", () => {
  const FULL = { x: 0, y: 0, w: 1600, h: 1000 };
  const VIEWPORT = { w: 800, h: 500 };

  it("is identity for an untouched gesture", () => {
    expect(foldTransform(FULL, { x: 0, y: 0, k: 1 }, VIEWPORT)).toEqual(FULL);
  });

  it("panning right moves the viewBox left", () => {
    expect(foldTransform(FULL, { x: 100, y: 0, k: 1 }, VIEWPORT).x).toBeLessThan(0);
  });

  it("zooming in narrows the viewBox", () => {
    expect(foldTransform(FULL, { x: 0, y: 0, k: 2 }, VIEWPORT).w).toBe(800);
  });

  it("zooms about the centre, not the top-left corner", () => {
    const before = FULL.x + FULL.w / 2;
    const after = foldTransform(FULL, { x: 0, y: 0, k: 2 }, VIEWPORT);
    expect(after.x + after.w / 2).toBeCloseTo(before, 5);
  });
});

describe("clampViewBox", () => {
  it("refuses to zoom in past the limit", () => {
    expect(clampViewBox({ x: 0, y: 0, w: 10, h: 6 }, PLAN, PHONE).w).toBe(PLAN.w / 10);
  });

  it("refuses to zoom out past the limit", () => {
    expect(clampViewBox({ x: 0, y: 0, w: 99999, h: 6 }, PLAN, PHONE).w).toBeLessThanOrEqual(
      PLAN.w * 1.6,
    );
  });

  it("holds the container aspect ratio while clamping", () => {
    const vb = clampViewBox({ x: 0, y: 0, w: 10, h: 999 }, PLAN, PHONE);
    expect(vb.w / vb.h).toBeCloseTo(PHONE.w / PHONE.h, 5);
  });

  it("stops the plan being dragged completely off screen", () => {
    const vb = clampViewBox({ x: 99999, y: 99999, w: 400, h: 746 }, PLAN, PHONE);
    expect(vb.x).toBeLessThan(PLAN.w);
    expect(vb.y).toBeLessThan(PLAN.h);
  });

  it("leaves a already-valid view alone", () => {
    const start = coverViewBox(PLAN, PHONE);
    const clamped = clampViewBox(start, PLAN, PHONE);
    expect(clamped.w).toBeCloseTo(start.w, 5);
    expect(clamped.h).toBeCloseTo(start.h, 5);
  });
});

describe("toCss", () => {
  it("uses translate3d so the layer is composited", () => {
    expect(toCss({ x: 5, y: 6, k: 2 })).toBe("translate3d(5px, 6px, 0) scale(2)");
  });
});

describe("shouldRenderLabels", () => {
  it("hides 300 text nodes when a desk would be a few pixels across", () => {
    // Whole 1600-unit plan squeezed into a 375px phone: ~7px per desk.
    expect(shouldRenderLabels({ x: 0, y: 0, w: 1600, h: 1000 }, PHONE)).toBe(false);
  });

  it("shows them at the default phone zoom", () => {
    expect(shouldRenderLabels(coverViewBox(PLAN, PHONE), PHONE)).toBe(true);
  });

  it("judges legibility by rendered size, not a fraction of the plan", () => {
    // Same view; only the container differs. A wider container makes the same
    // desks bigger on screen, so labels become worth drawing.
    const vb = { x: 0, y: 0, w: 1600, h: 1000 };
    expect(shouldRenderLabels(vb, { w: 375, h: 700 })).toBe(false);
    expect(shouldRenderLabels(vb, { w: 1400, h: 900 })).toBe(true);
  });
});
