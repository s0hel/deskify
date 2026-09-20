import type { DayAvailability } from "../api/hooks";
import { Chevron } from "../ui/bits";

/**
 * The hero card answers one question: am I sorted for this day?
 *
 * Booked and not-booked are different cards rather than one card with a
 * conditional line, because the answer changes what the card is *for* -- find
 * your desk, or get one.
 *
 * The card does NOT carry "Book a space". That button belongs to the screen
 * and is always in the same place, so the thing you came to do does not move
 * depending on whether you happen to have a desk already. What the card keeps
 * is the action only it can offer: showing you where your desk is.
 */
export function TodayCard({
  day,
  dayLabel,
  siteName,
  onShowPlan,
}: {
  day: DayAvailability | undefined;
  dayLabel: string;
  siteName: string;
  onShowPlan: () => void;
}) {
  if (!day) return null;

  if (day.my_booking_id) {
    return (
      <section className="card">
        <span className="eyebrow eyebrow--clay">Your desk · {dayLabel}</span>
        <h2 className="display tabular" style={{ marginTop: 4 }}>
          {day.my_resource_name}
        </h2>
        <p className="meta" style={{ marginTop: 6 }}>
          {siteName} · All day
        </p>
        <button className="btn btn--quiet" style={{ marginTop: 16 }} onClick={onShowPlan}>
          Show on the plan
        </button>
      </section>
    );
  }

  const full = day.free === 0;
  return (
    <section className="card">
      <span className="eyebrow">{dayLabel}</span>
      <h2 className="title" style={{ marginTop: 6 }}>
        {full ? "No desks left" : "You have no desk yet"}
      </h2>
      <p className="meta" style={{ marginTop: 6 }}>
        {full ? (
          `All ${day.total} desks are taken.`
        ) : (
          <>
            <span className="count-free tabular">{day.free} free</span> of {day.total} at{" "}
            {siteName}.
          </>
        )}
      </p>
    </section>
  );
}

export function NextInOffice({
  days,
  labelFor,
  onPick,
}: {
  days: DayAvailability[];
  labelFor: (iso: string) => string;
  onPick: (iso: string) => void;
}) {
  const upcoming = days.filter((d) => d.my_booking_id).slice(0, 3);
  if (upcoming.length === 0) return null;

  return (
    <section className="section pad">
      <span className="eyebrow">Next in the office</span>
      <div className="stack">
        {upcoming.map((d) => (
          <button key={d.date} className="row-card" onClick={() => onPick(d.date)}>
            <span>
              <span style={{ fontWeight: 600 }}>{labelFor(d.date)}</span>
              <br />
              <span className="meta tabular">{d.my_resource_name}</span>
            </span>
            <Chevron />
          </button>
        ))}
      </div>
    </section>
  );
}
