import { describe, expect, it } from "vitest";

import { clampViewBox, foldTransform, shouldRenderLabels, toCss } from "./viewbox";

const PLAN = { w: 1600, h: 1000 };
const FULL = { x: 0, y: 0, w: 1600, h: 1000 };
const VIEWPORT = { w: 800, h: 500 };

describe("foldTransform", () => {
  it("is identity for an untouched gesture", () => {
    expect(foldTransform(FULL, { x: 0, y: 0, k: 1 }, VIEWPORT)).toEqual(FULL);
  });

  it("panning right moves the viewBox left", () => {
    const vb = foldTransform(FULL, { x: 100, y: 0, k: 1 }, VIEWPORT);
    expect(vb.x).toBeLessThan(0);
    expect(vb.w).toBe(FULL.w);
  });

  it("zooming in narrows the viewBox", () => {
    const vb = foldTransform(FULL, { x: 0, y: 0, k: 2 }, VIEWPORT);
    expect(vb.w).toBe(800);
  });
});

describe("clampViewBox", () => {
  it("refuses to zoom in past the limit", () => {
    expect(clampViewBox({ ...FULL, w: 10, h: 6 }, PLAN).w).toBe(PLAN.w / 8);
  });

  it("refuses to zoom out past the limit", () => {
    expect(clampViewBox({ ...FULL, w: 99999, h: 60000 }, PLAN).w).toBe(PLAN.w * 1.5);
  });

  it("keeps aspect ratio while clamping", () => {
    const vb = clampViewBox({ ...FULL, w: 10, h: 999 }, PLAN);
    expect(vb.h / vb.w).toBeCloseTo(PLAN.h / PLAN.w);
  });
});

describe("toCss", () => {
  it("uses translate3d so the layer is composited", () => {
    expect(toCss({ x: 5, y: 6, k: 2 })).toBe("translate3d(5px, 6px, 0) scale(2)");
  });
});

describe("shouldRenderLabels", () => {
  it("hides 300 text nodes when zoomed out", () => {
    expect(shouldRenderLabels(FULL, PLAN)).toBe(false);
  });
  it("shows them when zoomed in", () => {
    expect(shouldRenderLabels({ ...FULL, w: 400 }, PLAN)).toBe(true);
  });
});
