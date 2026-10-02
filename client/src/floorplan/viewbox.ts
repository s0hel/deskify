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

/** How far in and out we let the user zoom: in, as a fraction of the plan
 *  width; out, as a multiple of the view that fits the whole plan. */
const MIN_SPAN = 1 / 10;
const MAX_SPAN = 1.2;

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
 * Zoom by `factor` (>1 is in) keeping the plan point under `point` -- a
 * position in container px -- exactly where it is. The wheel/trackpad zoom:
 * on a desktop, zooming toward the middle of the screen when the pointer is on
 * a desk in the corner reads as the plan sliding away from you.
 *
 * Not clamped; the caller clamps, as it does for every other gesture.
 */
export function zoomAt(vb: ViewBox, factor: number, point: { x: number; y: number }, container: Size): ViewBox {
  const fx = point.x / container.w;
  const fy = point.y / container.h;
  const w = vb.w / factor;
  const h = vb.h / factor;
  return {
    x: vb.x + fx * vb.w - fx * w,
    y: vb.y + fy * vb.h - fy * h,
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
  // Out as far as the WHOLE plan, with room to spare, whatever the container's
  // shape. This used to be a cap on width and a separate cap on height
  // (MAX_SPAN x the plan's), and in a tall container the height cap bit
  // first: a phone could never back out past about a third of a wide floor
  // like Tampa 5F, by pinch or by anything else.
  const containW = Math.max(plan.w, plan.h * aspect);
  const maxW = containW * MAX_SPAN;

  const w = Math.min(Math.max(vb.w, minW), maxW);
  const h = w / aspect;

  return { w, h, x: clampAxis(vb.x, w, plan.w), y: clampAxis(vb.y, h, plan.h) };
}

/** One axis of the pan clamp. */
function clampAxis(start: number, span: number, planSpan: number): number {
  // Zoomed out past the plan on this axis: centre it. Pinning it to one edge
  // leaves all the empty space on the other side, which reads as a bug.
  if (span >= planSpan) return (planSpan - span) / 2;
  // A little slack on each side so desks at the plan's edge can be centred and
  // tapped. Kept small: more than this and a focused desk sits against a wide
  // empty band, which reads as a rendering bug.
  const slack = span * 0.12;
  return Math.min(Math.max(start, -slack), planSpan - span + slack);
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
