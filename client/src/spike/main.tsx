/**
 * The R8 gate, runnable.
 *
 * PRD §9.1 asks for 300 desks, first render under 1.0s, and sustained 60fps
 * pan/zoom on mid-tier Android. This page measures exactly that against the
 * real FloorPlan component, and prints numbers rather than an impression.
 *
 *   npm run dev -- --host      then open /spike.html on the device
 *
 * Phase 0 exits when this passes on real low-end hardware, not on a laptop.
 */

import { StrictMode, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import { FloorPlan, type Desk, type DeskState } from "../floorplan/FloorPlan";
import "../styles.css";

const DESKS = 300;
const PAN_FRAMES = 240;
//: rAF frames are not comparable until the compositor layer exists and the
//: first raster is done. Measuring them produces a meaningless "worst frame".
const WARMUP_FRAMES = 5;
//: A throttled rAF (~1Hz) would take minutes to collect PAN_FRAMES. Abort well
//: before that and say why.
const WALL_CLOCK_BUDGET_MS = 15_000;

function makeDesks(n: number): Desk[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `d${i}`,
    name: `4F-A-${String(i + 1).padStart(3, "0")}`,
    plan_x: 60 + (i % 20) * 70,
    plan_y: 70 + Math.floor(i / 20) * 70,
    kind: "desk" as const,
  }));
}

interface Report {
  valid: boolean;
  invalidReason?: string;
  firstRenderMs: number;
  p50: number;
  p95: number;
  worst: number;
  overBudgetPct: number;
  frames: number;
}

function percentile(sorted: number[], p: number): number {
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))];
}

function Spike() {
  const desks = useMemo(() => makeDesks(DESKS), []);
  const states = useMemo<Record<string, DeskState>>(
    () => Object.fromEntries(desks.map((d, i) => [d.id, i % 7 ? "free" : "booked"])),
    [desks],
  );
  const [report, setReport] = useState<Report | null>(null);
  const mountedAt = useRef(performance.now());

  useEffect(() => {
    const firstRenderMs = performance.now() - mountedAt.current;
    const wrapper = document.querySelector<HTMLElement>(".floorplan")!;

    // Drive the same style writes a real drag produces, one per frame, and
    // time the frames. This measures the COMPOSITED path (rule 2), which is
    // the one that has to hold 60fps.
    const gaps: number[] = [];
    let last = performance.now();
    let i = 0;
    wrapper.style.willChange = "transform";

    // A backgrounded tab throttles rAF to ~1Hz, which would report a garbage
    // worst frame and could fail a run that was actually fine. A gate that
    // reports noise is worse than no gate, so we invalidate instead.
    let hidden = document.visibilityState === "hidden";
    const onVisibility = () => {
      if (document.visibilityState === "hidden") hidden = true;
    };
    document.addEventListener("visibilitychange", onVisibility);

    const startedAt = performance.now();

    function abort(reason: string) {
      wrapper.style.transform = "";
      wrapper.style.willChange = "";
      document.removeEventListener("visibilitychange", onVisibility);
      setReport({
        valid: false,
        invalidReason: reason,
        firstRenderMs,
        p50: 0,
        p95: 0,
        worst: 0,
        overBudgetPct: 0,
        frames: gaps.length,
      });
    }

    if (hidden) {
      // Bail immediately rather than grinding through a throttled run.
      abort("the page is not visible; rAF is throttled. Run it in a foreground tab.");
      return () => document.removeEventListener("visibilitychange", onVisibility);
    }

    function frame() {
      const now = performance.now();
      if (hidden || now - startedAt > WALL_CLOCK_BUDGET_MS) {
        abort(
          hidden
            ? "the tab was backgrounded mid-run; rerun with the page visible"
            : "the run exceeded its wall-clock budget, which means rAF was throttled",
        );
        return;
      }
      if (i >= WARMUP_FRAMES) gaps.push(now - last);
      last = now;
      const t = Math.sin(i / 20) * 200;
      wrapper.style.transform = `translate3d(${t}px, ${t / 2}px, 0) scale(${1 + Math.sin(i / 40) * 0.4})`;
      if (++i < PAN_FRAMES) {
        requestAnimationFrame(frame);
      } else {
        wrapper.style.transform = "";
        wrapper.style.willChange = "";
        document.removeEventListener("visibilitychange", onVisibility);
        const sorted = [...gaps].sort((a, b) => a - b);
        setReport({
          valid: !hidden,
          invalidReason: hidden
            ? "the tab was backgrounded mid-run; rerun with the page visible"
            : undefined,
          firstRenderMs,
          p50: percentile(sorted, 0.5),
          p95: percentile(sorted, 0.95),
          worst: sorted[sorted.length - 1],
          overBudgetPct: (gaps.filter((g) => g > 16.7).length / gaps.length) * 100,
          frames: gaps.length,
        });
      }
    }
    requestAnimationFrame(frame);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  const pass =
    report &&
    report.valid &&
    report.firstRenderMs < 1000 &&
    report.p95 <= 20 &&
    report.overBudgetPct < 10;

  return (
    <main>
      <h1 style={{ font: "600 16px system-ui", margin: "8px" }}>
        Floor plan spike — {DESKS} desks
      </h1>
      {report ? (
        <pre
          style={{
            margin: 8,
            padding: 12,
            background: !report.valid ? "#fdf6e3" : pass ? "#e7f6ee" : "#fdecec",
            color: "#14181d",
            borderRadius: 8,
            fontSize: 13,
          }}
        >
{`first render   ${report.firstRenderMs.toFixed(1)} ms   (budget < 1000)
frame p50      ${report.p50.toFixed(2)} ms
frame p95      ${report.p95.toFixed(2)} ms   (budget <= 20)
worst frame    ${report.worst.toFixed(2)} ms
over 16.7ms    ${report.overBudgetPct.toFixed(1)} %   (budget < 10)
frames         ${report.frames}

${report.valid ? (pass ? "PASS" : "FAIL") : `INVALID — ${report.invalidReason}`}
${report.valid ? "Record the device and OS alongside this." : ""}`}
        </pre>
      ) : (
        <p style={{ margin: 8 }}>measuring…</p>
      )}
      <FloorPlan planWidth={1600} planHeight={1000} desks={desks} states={states} />
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Spike />
  </StrictMode>,
);
