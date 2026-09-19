/**
 * Pan/zoom maths, kept pure so it can be tested without a DOM.
 * TDD §9.3.
 */

export interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Transform {
  x: number;
  y: number;
  k: number;
}

export const IDENTITY: Transform = { x: 0, y: 0, k: 1 };

/**
 * Fold a gesture transform into the viewBox.
 *
 * This runs ONCE, on gesture end. During the gesture the same transform is a
 * composited CSS transform on the wrapper; folding it back into the viewBox is
 * what re-rasterizes the SVG crisp at the new scale.
 */
export function foldTransform(vb: ViewBox, t: Transform, viewportPx: { w: number; h: number }): ViewBox {
  const scaleX = vb.w / viewportPx.w;
  const scaleY = vb.h / viewportPx.h;
  return {
    x: vb.x - (t.x * scaleX) / t.k,
    y: vb.y - (t.y * scaleY) / t.k,
    w: vb.w / t.k,
    h: vb.h / t.k,
  };
}

/** Keep the plan on screen and within sane zoom limits. */
export function clampViewBox(vb: ViewBox, plan: { w: number; h: number }): ViewBox {
  const minW = plan.w / 8; // max zoom in
  const maxW = plan.w * 1.5; // max zoom out
  const w = Math.min(Math.max(vb.w, minW), maxW);
  const h = w * (plan.h / plan.w);
  return {
    w,
    h,
    x: Math.min(Math.max(vb.x, -plan.w * 0.25), plan.w - w * 0.75),
    y: Math.min(Math.max(vb.y, -plan.h * 0.25), plan.h - h * 0.75),
  };
}

export function toCss(t: Transform): string {
  // translate3d, not translate: forces a compositor layer.
  return `translate3d(${t.x}px, ${t.y}px, 0) scale(${t.k})`;
}

/** Labels cost more than the rects they annotate; only draw them zoomed in. */
export function shouldRenderLabels(vb: ViewBox, plan: { w: number }): boolean {
  return vb.w < plan.w * 0.4;
}
