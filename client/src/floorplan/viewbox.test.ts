import { describe, expect, it } from "vitest";

import {
  clampViewBox,
  coverViewBox,
  foldTransform,
  pinchTransform,
  shouldRenderLabels,
  toCss,
  zoomAt,
} from "./viewbox";

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

  it("lands exactly where the CSS transform showed the plan, so nothing jumps", () => {
    // toCss draws local px p at t + k*p (transform-origin 0 0). Whatever plan
    // point was under a screen position mid-gesture must be under it after.
    const under = (vb: typeof FULL, sx: number, sy: number) => ({
      x: vb.x + (sx / VIEWPORT.w) * vb.w,
      y: vb.y + (sy / VIEWPORT.h) * vb.h,
    });
    for (const t of [{ x: 0, y: 0, k: 2 }, { x: -130, y: 40, k: 1.7 }, { x: 90, y: -20, k: 0.6 }]) {
      const after = foldTransform(FULL, t, VIEWPORT);
      for (const [px, py] of [[0, 0], [400, 250], [731, 12]]) {
        const sx = t.x + t.k * px;
        const sy = t.y + t.k * py;
        expect(under(after, sx, sy).x).toBeCloseTo(under(FULL, px, py).x, 6);
        expect(under(after, sx, sy).y).toBeCloseTo(under(FULL, px, py).y, 6);
      }
    }
  });
});

describe("clampViewBox", () => {
  it("refuses to zoom in past the limit", () => {
    expect(clampViewBox({ x: 0, y: 0, w: 10, h: 6 }, PLAN, PHONE).w).toBe(PLAN.w / 10);
  });

  it("refuses to zoom out past the limit", () => {
    expect(clampViewBox({ x: 0, y: 0, w: 99999, h: 6 }, PLAN, PHONE).w).toBeLessThanOrEqual(
      PLAN.w * 1.2,
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

  it("lets a tall container zoom out to the whole of a wide plan", () => {
    // Tampa 5F on a phone: the old height cap stopped this at a third.
    const wide = { w: 1900, h: 730 };
    const vb = clampViewBox({ x: 0, y: 0, w: 99999, h: 99999 }, wide, PHONE);
    expect(vb.w).toBeGreaterThanOrEqual(wide.w);
  });

  it("centres a plan that is smaller than the view instead of pinning it left", () => {
    const vb = clampViewBox({ x: -5000, y: 0, w: 2400, h: 1200 }, PLAN, WIDE);
    expect(vb.x + vb.w / 2).toBeCloseTo(PLAN.w / 2, 5);
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

describe("zoomAt", () => {
  const VB = { x: 100, y: 50, w: 800, h: 400 };
  const BOX = { w: 400, h: 200 };

  it("keeps the plan point under the pointer where it is", () => {
    const p = { x: 300, y: 50 };
    const under = (vb: typeof VB) => ({
      x: vb.x + (p.x / BOX.w) * vb.w,
      y: vb.y + (p.y / BOX.h) * vb.h,
    });
    for (const factor of [2, 0.5, 1.25]) {
      const next = zoomAt(VB, factor, p, BOX);
      expect(under(next).x).toBeCloseTo(under(VB).x, 6);
      expect(under(next).y).toBeCloseTo(under(VB).y, 6);
    }
  });

  it("zooms in by shrinking the span, out by growing it, and keeps the aspect", () => {
    expect(zoomAt(VB, 2, { x: 0, y: 0 }, BOX).w).toBe(400);
    expect(zoomAt(VB, 0.5, { x: 0, y: 0 }, BOX).w).toBe(1600);
    const out = zoomAt(VB, 0.5, { x: 123, y: 45 }, BOX);
    expect(out.w / out.h).toBeCloseTo(VB.w / VB.h, 6);
  });

  it("zooms out far enough to see the whole plan once clamped", () => {
    // The point of the wheel: a phone-shaped view of a wide floor must be
    // able to back out until the full width is on screen.
    let vb = coverViewBox(PLAN, PHONE);
    for (let i = 0; i < 30; i++) vb = clampViewBox(zoomAt(vb, 0.8, { x: 187, y: 350 }, PHONE), PLAN, PHONE);
    expect(vb.w).toBeGreaterThanOrEqual(PLAN.w);
  });
});

describe("pinchTransform", () => {
  const VB = { x: 200, y: 100, w: 800, h: 500 };
  const VIEW = { w: 400, h: 250 };
  // Plan point under a wrapper-px position, for a viewBox (no transform).
  const under = (vb: typeof VB, x: number, y: number) => ({
    x: vb.x + (x / VIEW.w) * vb.w,
    y: vb.y + (y / VIEW.h) * vb.h,
  });

  it("keeps the plan point under the fingers there, through the fold", () => {
    // Fingers land around (120, 80), spread apart, and drift right.
    const start = { dist: 100, k: 1, px: 120, py: 80 };
    const before = under(VB, 120, 80);
    const a = { x: 60, y: 90 };
    const b = { x: 260, y: 90 }; // midpoint (160, 90), twice as far apart
    const t = pinchTransform(start, a, b);
    expect(t.k).toBeCloseTo(2, 6);
    const after = foldTransform(VB, t, VIEW);
    // The same plan point is now under the fingers' NEW midpoint.
    expect(under(after, 160, 90).x).toBeCloseTo(before.x, 6);
    expect(under(after, 160, 90).y).toBeCloseTo(before.y, 6);
  });

  it("is the identity for fingers that have not moved", () => {
    const start = { dist: 100, k: 1, px: 150, py: 75 };
    const t = pinchTransform(start, { x: 100, y: 75 }, { x: 200, y: 75 });
    expect(t.k).toBeCloseTo(1, 6);
    expect(t.x).toBeCloseTo(0, 6);
    expect(t.y).toBeCloseTo(0, 6);
  });
});
