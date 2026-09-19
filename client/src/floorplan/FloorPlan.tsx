/**
 * The floor plan. One component, viewer and editor modes (TDD §9.3, §9.5).
 * This is the screen risk R8 is about.
 *
 * THE RULES, in the order they matter:
 *   1. The SVG renders ONCE. Pan/zoom never touches React state.
 *   2. During a gesture: composited CSS transform on the wrapper. Cheap, smooth.
 *   3. On gesture end: fold into the viewBox, reset the CSS transform. One
 *      re-raster, crisp. This is the ONLY React state update in the interaction.
 *   4. Desk state changes are setAttribute calls, not re-renders.
 *   5. Hit testing is one delegated listener, not 300 React handlers.
 *
 * Break any of these and it will not hold 60fps on mid-tier Android.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  IDENTITY,
  type Size,
  type Transform,
  type ViewBox,
  clampViewBox,
  coverViewBox,
  foldTransform,
  shouldRenderLabels,
  toCss,
} from "./viewbox";

export interface Desk {
  id: string;
  name: string;
  plan_x: number;
  plan_y: number;
  kind: "desk" | "room";
}

export type DeskState = "free" | "booked" | "mine" | "unavailable" | "assigned";

export interface FloorPlanProps {
  planWidth: number;
  planHeight: number;
  desks: Desk[];
  states: Record<string, DeskState>;
  planImageUrl?: string;
  onSelect?: (deskId: string) => void;
  editable?: boolean;
}

const DESK_R = 16;
const ROOM_R = 26;

export function FloorPlan({
  planWidth,
  planHeight,
  desks,
  states,
  planImageUrl,
  onSelect,
  editable = false,
}: FloorPlanProps) {
  const wrapper = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const gesture = useRef<Transform>({ ...IDENTITY });
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinchStart = useRef<{ dist: number; k: number } | null>(null);

  const plan = useMemo<Size>(
    () => ({ w: planWidth, h: planHeight }),
    [planWidth, planHeight],
  );
  const lastSize = useRef<Size | null>(null);
  const [viewBox, setViewBox] = useState<ViewBox>({ x: 0, y: 0, w: planWidth, h: planHeight });
  const withLabels = lastSize.current
    ? shouldRenderLabels(viewBox, lastSize.current)
    : false;

  // Fill the container on mount and whenever it is resized -- a rotated phone
  // or a split-screen pane must not leave the plan letterboxed.
  useEffect(() => {
    const el = wrapper.current;
    if (!el) return;

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width < 1 || height < 1) return;
      const prev = lastSize.current;
      if (prev && Math.abs(prev.w - width) < 1 && Math.abs(prev.h - height) < 1) return;
      lastSize.current = { w: width, h: height };
      setViewBox(coverViewBox(plan, lastSize.current));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [plan]);

  // -- Rule 4: state changes are attribute writes, never a React re-render. ----
  useEffect(() => {
    const root = svg.current;
    if (!root) return;
    for (const [id, state] of Object.entries(states)) {
      const node = root.querySelector<SVGCircleElement>(
        `.desks [data-resource-id="${id}"]`,
      );
      if (!node) continue;
      const isRoom = node.classList.contains("desk--room");
      node.setAttribute("class", isRoom ? `desk desk--room desk--${state}` : `desk desk--${state}`);
    }
  }, [states]);

  const applyGesture = useCallback(() => {
    if (wrapper.current) wrapper.current.style.transform = toCss(gesture.current);
  }, []);

  const commit = useCallback(() => {
    const el = wrapper.current;
    if (!el) return;
    const t = gesture.current;
    if (t.x === 0 && t.y === 0 && t.k === 1) return;

    const rect = el.getBoundingClientRect();
    const size = { w: rect.width, h: rect.height };
    const next = clampViewBox(foldTransform(viewBox, t, size), plan, size);

    gesture.current = { ...IDENTITY };
    el.style.transform = "";
    el.style.willChange = "";
    setViewBox(next); // Rule 3: the one state update
  }, [viewBox, plan]);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (wrapper.current) wrapper.current.style.willChange = "transform";
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinchStart.current = {
        dist: Math.hypot(a.x - b.x, a.y - b.y),
        k: gesture.current.k,
      };
    }
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!pointers.current.has(e.pointerId)) return;
      const prev = pointers.current.get(e.pointerId)!;
      pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });

      if (pointers.current.size === 2 && pinchStart.current) {
        const [a, b] = [...pointers.current.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        gesture.current.k = pinchStart.current.k * (dist / pinchStart.current.dist);
      } else {
        gesture.current.x += e.clientX - prev.x;
        gesture.current.y += e.clientY - prev.y;
      }
      applyGesture(); // Rule 2: one style write per frame, no React
    },
    [applyGesture],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent) => {
      pointers.current.delete(e.pointerId);
      if (pointers.current.size < 2) pinchStart.current = null;
      if (pointers.current.size === 0) commit();
    },
    [commit],
  );

  // -- Rule 5: one delegated listener for all 300 nodes. ----------------------
  const onClick = useCallback(
    (e: React.MouseEvent) => {
      const id = (e.target as Element).getAttribute?.("data-resource-id");
      if (id) onSelect?.(id);
    },
    [onSelect],
  );

  return (
    <div
      ref={wrapper}
      className="floorplan"
      data-editable={editable || undefined}
      style={{ touchAction: "none", transformOrigin: "0 0", willChange: "auto" }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onClick={onClick}
    >
      <svg
        ref={svg}
        viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
        width="100%"
        height="100%"
        /* The plan is decorative: the list view is the accessible path, and it
           is not a fallback (FR-10.5, TDD §9.4). */
        aria-hidden="true"
      >
        {planImageUrl && (
          <image href={planImageUrl} x={0} y={0} width={plan.w} height={plan.h} />
        )}
        <g className="desks">
          {desks.map((d) => {
            const state = states[d.id] ?? "free";
            return (
              <circle
                key={d.id}
                data-resource-id={d.id}
                className={
                  d.kind === "room"
                    ? `desk desk--room desk--${state}`
                    : `desk desk--${state}`
                }
                cx={d.plan_x}
                cy={d.plan_y}
                r={d.kind === "room" ? ROOM_R : DESK_R}
              />
            );
          })}
        </g>
        {/* Your own desk gets a ring, so it is findable without reading labels.
            Drawn in its own layer and never hit-tested. */}
        <g className="rings" pointerEvents="none">
          {desks
            .filter((d) => states[d.id] === "mine")
            .map((d) => (
              <circle
                key={d.id}
                className="desk-ring"
                cx={d.plan_x}
                cy={d.plan_y}
                r={(d.kind === "room" ? ROOM_R : DESK_R) + 7}
              />
            ))}
        </g>
        {withLabels && (
          <g className="labels" pointerEvents="none">
            {desks.map((d) => (
              <text
                key={d.id}
                x={d.plan_x}
                y={d.plan_y + (d.kind === "room" ? ROOM_R : DESK_R) + 16}
                fontSize={13}
                textAnchor="middle"
                fill="currentColor"
                opacity={0.55}
              >
                {d.name}
              </text>
            ))}
          </g>
        )}
      </svg>
    </div>
  );
}
