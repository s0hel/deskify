import type { DayAvailability } from "../api/hooks";

/**
 * Two marks, two facts: the bar says whether the office has room, the dot says
 * whether *you* have a day there. Conflating them into one colour is what makes
 * these strips unreadable.
 */
export function WeekStrip({
  days,
  selected,
  todayIso,
  onPick,
}: {
  days: DayAvailability[];
  selected: string;
  todayIso: string;
  onPick: (iso: string) => void;
}) {
  return (
    <div className="week" role="group" aria-label="Choose a day">
      {days.map((d) => {
        const on = d.date === selected;
        const isToday = d.date === todayIso;
        const [, month, dom] = d.date.split("-");
        const dow = new Date(Date.UTC(+d.date.slice(0, 4), +month - 1, +dom)).toLocaleDateString(
          "en-GB",
          { weekday: "short", timeZone: "UTC" },
        );
        const booked = Boolean(d.my_booking_id);
        const away = !booked && Boolean(d.declaration && d.declaration !== "office");

        return (
          <button
            key={d.date}
            className={`daycard${on ? " daycard--on" : ""}`}
            aria-pressed={on}
            aria-label={
              `${dow} ${Number(dom)}. ${d.free} of ${d.total} free.` +
              (booked ? ` You have ${d.my_resource_name ?? "a desk"}.` : "")
            }
            onClick={() => onPick(d.date)}
          >
            <span className="daycard__dow">{isToday ? "TODAY" : dow.toUpperCase()}</span>
            <span className="daycard__num">{Number(dom)}</span>
            <span className={d.free > 0 ? "daycard__bar" : "daycard__bar daycard__bar--none"} />
            <span
              className={
                booked
                  ? "daycard__dot daycard__dot--booked"
                  : away
                    ? "daycard__dot daycard__dot--away"
                    : "daycard__dot daycard__dot--none"
              }
            />
          </button>
        );
      })}
    </div>
  );
}
