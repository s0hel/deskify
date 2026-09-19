/**
 * Pan/zoom maths, kept pure so it can be tested without a DOM.
 * TDD §9.3.
 *
 * The viewBox always carries the CONTAINER's aspect ratio, never the plan's.
 * That is what lets the plan fill a tall phone screen and be panned, instead of
 * being letterboxed into a strip with dead space under it -- and it keeps
 * foldTransform's px-to-plan-unit conversion correct on both axes, which a
 * preserveAspectRatio="slice" would quietly break.
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

export interface Size {
  w: number;
  h: number;
}

export const IDENTITY: Transform = { x: 0, y: 0, k: 1 };

/** How far in and out we let the user zoom, as a multiple of the plan width. */
const MIN_SPAN = 1 / 10;
const MAX_SPAN = 1.6;

/**
 * The starting view: fill the container with plan, centred, showing as much as
 * possible without letterboxing. The SVG equivalent of `object-fit: cover`.
 */
export function coverViewBox(plan: Size, container: Size): ViewBox {
  const aspect = container.w / container.h;
  // Take the axis that would leave a gap and let the other overflow.
  let w = plan.w;
  let h = w / aspect;
  if (h > plan.h) {
    h = plan.h;
    w = h * aspect;
  }
  return { x: (plan.w - w) / 2, y: (plan.h - h) / 2, w, h };
}

/**
 * Fold a gesture transform into the viewBox.
 *
 * Runs ONCE, on gesture end. During the gesture the same transform is a
 * composited CSS transform on the wrapper; folding it back into the viewBox is
 * what re-rasterizes the SVG crisp at the new scale.
 */
export function foldTransform(vb: ViewBox, t: Transform, viewportPx: Size): ViewBox {
  const unitsPerPxX = vb.w / viewportPx.w;
  const unitsPerPxY = vb.h / viewportPx.h;
  const w = vb.w / t.k;
  const h = vb.h / t.k;
  // Zoom is anchored at the centre, so the origin shifts by half the change.
  return {
    x: vb.x - t.x * unitsPerPxX + (vb.w - w) / 2,
    y: vb.y - t.y * unitsPerPxY + (vb.h - h) / 2,
    w,
    h,
  };
}

/**
 * Keep the view within sane zoom limits and stop the plan being dragged
 * entirely off screen, while PRESERVING the container's aspect ratio.
 */
export function clampViewBox(vb: ViewBox, plan: Size, container: Size): ViewBox {
  const aspect = container.w / container.h;
  const minW = plan.w * MIN_SPAN;
  const maxW = plan.w * MAX_SPAN;

  let w = Math.min(Math.max(vb.w, minW), maxW);
  let h = w / aspect;
  // Re-derive width if the height clamp bites, so the aspect always holds.
  if (h > plan.h * MAX_SPAN) {
    h = plan.h * MAX_SPAN;
    w = h * aspect;
  }

  // Allow a quarter-view of slack on each side, so edge desks are reachable.
  const slackX = w * 0.25;
  const slackY = h * 0.25;
  return {
    w,
    h,
    x: Math.min(Math.max(vb.x, -slackX), Math.max(-slackX, plan.w - w + slackX)),
    y: Math.min(Math.max(vb.y, -slackY), Math.max(-slackY, plan.h - h + slackY)),
  };
}

export function toCss(t: Transform): string {
  // translate3d, not translate: forces a compositor layer.
  return `translate3d(${t.x}px, ${t.y}px, 0) scale(${t.k})`;
}

/** The on-screen diameter, in px, that a desk needs before its label is worth
 *  drawing. Below this the text is unreadable and 300 extra nodes are waste. */
const LABEL_LEGIBLE_PX = 20;

/** Plan-space diameter of a desk circle. Mirrors DESK_R in FloorPlan.tsx. */
const DESK_DIAMETER_UNITS = 32;

/**
 * Labels cost more than the circles they annotate, so draw them only when they
 * can actually be read.
 *
 * Legibility is a function of RENDERED size, which needs the container width as
 * well as the view: a fraction of the plan width says nothing on its own,
 * because a phone opens the plan already zoomed in (see coverViewBox).
 */
export function shouldRenderLabels(vb: ViewBox, container: Size): boolean {
  const pxPerUnit = container.w / vb.w;
  return DESK_DIAMETER_UNITS * pxPerUnit >= LABEL_LEGIBLE_PX;
}
