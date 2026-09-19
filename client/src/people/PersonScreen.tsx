import { ApiError } from "../api/client";
import { usePerson } from "../api/hooks";
import { weekdayLabel } from "../booking/dates";
import { Avatar } from "./Avatar";

/**
 * FR-5.2 -- one colleague's fortnight.
 *
 * In-office days are the only rows that do anything: "Sit near" takes you to
 * the plan for that day with their desk highlighted. A remote or leave day is
 * information; an office day is an opportunity.
 */
export function PersonScreen({
  userId,
  todayIso,
  onSitNear,
  onBack,
}: {
  userId: string;
  todayIso: string;
  onSitNear: (day: string, resourceId: string, floorId: string) => void;
  onBack: () => void;
}) {
  const person = usePerson(userId);

  if (person.isLoading) {
    return (
      <div className="scroll pad">
        <p className="meta">Loading…</p>
      </div>
    );
  }

  // A colleague who has hidden their days is a 404 by design (they must not be
  // distinguishable from someone who does not exist). Say so plainly.
  if (person.isError) {
    const notFound = person.error instanceof ApiError && person.error.status === 404;
    return (
      <div className="scroll pad">
        <div className="card">
          <span className="eyebrow">Not available</span>
          <p className="body" style={{ marginTop: 8 }}>
            {notFound
              ? "This person's days aren't visible to you."
              : "Couldn't load this person."}
          </p>
          <button className="btn btn--quiet" style={{ marginTop: 16 }} onClick={onBack}>
            Back
          </button>
        </div>
      </div>
    );
  }

  const p = person.data!;
  const office = p.schedule.filter((d) => d.kind === "office").length;

  return (
    <div className="scroll">
      <div className="pad person-head">
        <Avatar id={p.user_id} name={p.display_name} you={p.is_you} size={56} />
        <div>
          <h2 className="title">{p.display_name}</h2>
          <p className="meta">
            In the office {office} of the next {p.horizon_days} days
            {p.shared_teams.length > 0 && ` · ${p.shared_teams.join(", ")}`}
          </p>
        </div>
      </div>

      <section className="section pad">
        <span className="eyebrow">Next two weeks</span>
        <div className="stack">
          {p.schedule.map((d) => {
            const inOffice = d.kind === "office";
            return (
              <div key={d.date} className={inOffice ? "row-card" : "day-row"}>
                <span className="day-row__date">
                  <span className="daycard__dow">
                    {d.date === todayIso ? "TODAY" : weekdayLabel(d.date).split(" ")[0].toUpperCase()}
                  </span>
                  <br />
                  <span className="day-row__num tabular">{Number(d.date.slice(8))}</span>
                </span>

                <span className="day-row__body">
                  {inOffice ? (
                    <>
                      <span className="person__name">In the office</span>
                      <br />
                      <span className="meta tabular">
                        {[d.resource_name, d.floor_name].filter(Boolean).join(" · ")}
                      </span>
                    </>
                  ) : (
                    <span className="meta">
                      {d.kind === "remote"
                        ? "Working remotely"
                        : d.kind === "leave"
                          ? "On leave"
                          : "No plans yet"}
                    </span>
                  )}
                </span>

                {inOffice && d.resource_id && d.floor_id && !p.is_you && (
                  <button
                    className="sit-near"
                    onClick={() => onSitNear(d.date, d.resource_id!, d.floor_id!)}
                  >
                    Sit near →
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </section>
      <div style={{ height: 24 }} />
    </div>
  );
}
