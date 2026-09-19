import { Sheet } from "../ui/Sheet";

/**
 * FR-5.5 -- declare a day without booking a desk.
 *
 * This exists so the team grid is complete rather than merely silent about
 * you: "no booking" and "not coming in" look identical to a colleague
 * otherwise, and that ambiguity is what makes attendance data untrustworthy.
 */
const KINDS = [
  { value: "remote" as const, label: "Working remotely", detail: "You're working, just not here." },
  { value: "leave" as const, label: "On leave", detail: "Holiday, sick day, or otherwise away." },
  { value: "office" as const, label: "In the office", detail: "Coming in, without booking a desk yet." },
];

export function AbsenceSheet({
  dayLabel,
  current,
  busy,
  onChoose,
  onClear,
  onClose,
}: {
  dayLabel: string;
  current: string | null;
  busy: boolean;
  onChoose: (kind: "remote" | "leave" | "office") => void;
  onClear: () => void;
  onClose: () => void;
}) {
  return (
    <Sheet open onClose={onClose} labelledBy="absence-title">
      <h2 className="title" id="absence-title">
        {dayLabel}
      </h2>
      <p className="meta" style={{ marginTop: 4 }}>
        Tell your team what you're doing.
      </p>

      <div className="stack" style={{ marginTop: 14 }}>
        {KINDS.map((k) => {
          const chosen = current === k.value;
          return (
            <button
              key={k.value}
              className={chosen ? "choice choice--on" : "choice"}
              aria-pressed={chosen}
              disabled={busy}
              onClick={() => onChoose(k.value)}
            >
              <span className="choice__label">{k.label}</span>
              <span className="choice__detail">{k.detail}</span>
              {chosen && (
                <span className="choice__tick" aria-hidden="true">
                  ✓
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="sheet__actions">
        {current && (
          <button className="btn btn--quiet" disabled={busy} onClick={onClear}>
            Clear
          </button>
        )}
        <button className="btn btn--quiet" onClick={onClose}>
          Close
        </button>
      </div>
    </Sheet>
  );
}
