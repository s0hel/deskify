import type { ApiResource } from "../api/hooks";
import type { DeskState } from "../floorplan/FloorPlan";
import { Sheet } from "../ui/Sheet";

const STATE_TAG: Record<DeskState, { label: string; cls: string }> = {
  free: { label: "Free", cls: "tag tag--free" },
  mine: { label: "Yours", cls: "tag tag--yours" },
  booked: { label: "Taken", cls: "tag" },
  assigned: { label: "Assigned", cls: "tag" },
  unavailable: { label: "Out of service", cls: "tag" },
};

/** Turns the attributes jsonb into something a person would say. */
function features(attrs: Record<string, unknown>): string {
  const said: string[] = [];
  if (attrs.sit_stand) said.push("Sit/stand");
  if (typeof attrs.monitors === "number") {
    said.push(attrs.monitors === 1 ? "1 monitor" : `${attrs.monitors} monitors`);
  }
  if (attrs.window) said.push("By a window");
  if (attrs.accessible) said.push("Step-free access");
  if (attrs.vc) said.push("Video conferencing");
  if (attrs.whiteboard) said.push("Whiteboard");
  return said.length ? said.join(" · ") : "No listed features.";
}

export function DeskSheet({
  resource,
  state,
  dayLabel,
  busy,
  onBook,
  onCancel,
  onClose,
}: {
  resource: ApiResource | null;
  state: DeskState;
  dayLabel: string;
  busy: boolean;
  onBook: () => void;
  onCancel: () => void;
  onClose: () => void;
}) {
  if (!resource) return null;
  const tag = STATE_TAG[state];

  return (
    <Sheet open onClose={onClose} labelledBy="desk-sheet-title">
      <div className="sheet__head">
        <h2 className="title tabular" id="desk-sheet-title">
          {resource.name}
        </h2>
        <span className={tag.cls}>{tag.label}</span>
      </div>

      <p className="meta" style={{ marginTop: 6 }}>
        {resource.kind === "room" ? `Room · seats ${resource.capacity}` : "Desk"}
      </p>
      <p className="meta" style={{ marginTop: 10 }}>{features(resource.attributes)}</p>

      <div className="sheet__actions">
        {state === "free" && (
          <button className="btn btn--primary" onClick={onBook} disabled={busy}>
            {busy ? "Booking…" : `Book for ${dayLabel}`}
          </button>
        )}
        {state === "mine" && (
          <button className="btn btn--danger" onClick={onCancel} disabled={busy}>
            {busy ? "Cancelling…" : "Cancel this booking"}
          </button>
        )}
        {state !== "free" && state !== "mine" && (
          <p className="meta" style={{ margin: 0 }}>
            Pick another desk, or a different day.
          </p>
        )}
        <button className="btn btn--quiet" onClick={onClose}>
          Close
        </button>
      </div>
    </Sheet>
  );
}
