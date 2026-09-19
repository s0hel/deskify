/**
 * A refusal that offers a way forward.
 *
 * FR-6.9 requires the app to state which rule refused a booking. The reference
 * design goes further, and it is the better idea: name the problem in plain
 * language, then show the nearest days that would actually work and let the
 * user jump to one. A refusal that only explains is still a dead end.
 *
 * The machine code sits at the bottom in small type -- useful to support, not
 * addressed to the person reading it.
 */

import type { Denial } from "../api/client";
import type { DayAvailability } from "../api/hooks";
import { explain } from "../api/messages";
import { Sheet } from "../ui/Sheet";

export interface Refusal {
  code: string;
  denial: Denial | null;
  /** The day the user tried to book, so alternatives can exclude it. */
  attempted: string;
}

function headline(refusal: Refusal, dayLabel: string): string {
  switch (refusal.denial?.code ?? refusal.code) {
    case "CAPACITY_EXCEEDED":
      return `${dayLabel} is full`;
    case "RESOURCE_TAKEN":
      return "Someone got there first";
    case "SITE_CLOSED":
      return `The office is closed on ${dayLabel}`;
    case "BOOKING_HORIZON_EXCEEDED":
      return "That day is too far ahead";
    case "MAX_FUTURE_BOOKINGS":
      return "You have too many bookings";
    case "RESOURCE_UNAVAILABLE":
      return "That desk is out of service";
    case "ZONE_RESTRICTED":
      return "That area is reserved";
    case "DESK_ASSIGNED":
      return "That desk belongs to someone";
    case "OUTSIDE_OPENING_HOURS":
      return "The office is shut then";
    default:
      return "That booking was refused";
  }
}

export function RefusalSheet({
  refusal,
  dayLabel,
  alternatives,
  labelFor,
  onPickDay,
  onClose,
}: {
  refusal: Refusal;
  dayLabel: string;
  alternatives: DayAvailability[];
  labelFor: (iso: string) => string;
  onPickDay: (iso: string) => void;
  onClose: () => void;
}) {
  const detail = refusal.denial
    ? explain(refusal.denial)
    : explain({ code: refusal.code, rule_key: "", scope: "", params: {} });

  const best = alternatives[0];
  const code = refusal.denial?.rule_key
    ? `policy.${refusal.denial.rule_key}`
    : refusal.code.toLowerCase();

  return (
    <Sheet open onClose={onClose} labelledBy="refusal-title">
      <div className="sheet__head" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
        <span className="warn-icon" aria-hidden="true">!</span>
        <div>
          <h2 className="title" id="refusal-title">
            {headline(refusal, dayLabel)}
          </h2>
          <p className="meta" style={{ marginTop: 4 }}>{detail}</p>
        </div>
      </div>

      {alternatives.length > 0 && (
        <div className="alts">
          <span className="eyebrow">Nearest days with space</span>
          <div style={{ marginTop: 8 }}>
            {alternatives.map((d) => (
              <button key={d.date} className="alts__row" onClick={() => onPickDay(d.date)}>
                <span>{labelFor(d.date)}</span>
                <span className="alts__free tabular">{d.free} free</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="sheet__actions">
        {best && (
          <button className="btn btn--primary" onClick={() => onPickDay(best.date)}>
            Go to {labelFor(best.date)}
          </button>
        )}
        <button className="btn btn--quiet" onClick={onClose}>
          Close
        </button>
      </div>

      <p className="sheet__code">{code}</p>
    </Sheet>
  );
}
