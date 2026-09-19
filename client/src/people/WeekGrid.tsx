import { useState } from "react";

import { useTeamWeek, useTeams, type GridCell } from "../api/hooks";
import { addDays, isoWeekday, weekStart } from "../booking/dates";
import { Avatar } from "./Avatar";

/**
 * FR-5.4 -- a week grid of the team's planned presence.
 *
 * Forward-only, and the "previous week" control stops at the current week
 * rather than erroring. That boundary is a product position, not a limitation:
 * a grid you can scroll backwards through is a per-person attendance record,
 * which FR-9.5 and TDD §13.3 rule out.
 *
 * A teammate who has hidden their presence has no row here and is not counted
 * in the totals -- the server does that filtering, so this component cannot
 * accidentally reveal that someone is missing.
 */

const DOW = ["M", "T", "W", "T", "F", "S", "S"];

const CELL_LABEL: Record<GridCell["kind"], string> = {
  office: "In the office",
  remote: "Working remotely",
  leave: "On leave",
  none: "No plans",
};

export function WeekGrid({
  todayIso,
  onOpenPerson,
}: {
  todayIso: string;
  onOpenPerson: (userId: string) => void;
}) {
  const teams = useTeams(true);
  const [teamId, setTeamId] = useState<string | null>(null);
  const [start, setStart] = useState(() => weekStart(todayIso));

  const currentTeam = teamId ?? teams.data?.[0]?.id;
  const week = useTeamWeek(currentTeam, start);

  const thisWeek = weekStart(todayIso);
  const atEarliest = start <= thisWeek;

  if (teams.isLoading) {
    return <p className="meta pad">Loading…</p>;
  }
  if ((teams.data ?? []).length === 0) {
    return (
      <div className="pad">
        <div className="card">
          <span className="eyebrow">No teams</span>
          <p className="body" style={{ marginTop: 8 }}>
            You're not in a team yet, so there's no grid to show.
          </p>
        </div>
      </div>
    );
  }

  return (
    <>
      {(teams.data ?? []).length > 1 && (
        <div className="pad chiprow">
          {teams.data!.map((t) => (
            <button
              key={t.id}
              className={t.id === currentTeam ? "chip chip--on" : "chip"}
              aria-pressed={t.id === currentTeam}
              onClick={() => setTeamId(t.id)}
            >
              {t.name}
            </button>
          ))}
        </div>
      )}

      <div className="pad weeknav">
        <button
          className="weeknav__btn"
          onClick={() => setStart(addDays(start, -7))}
          disabled={atEarliest}
          aria-label="Previous week"
          title={atEarliest ? "The grid shows planned days, not past attendance" : undefined}
        >
          ‹
        </button>
        <span className="meta">
          {start === thisWeek ? "This week" : `Week of ${Number(start.slice(8))}`}
        </span>
        <button
          className="weeknav__btn"
          onClick={() => setStart(addDays(start, 7))}
          aria-label="Next week"
        >
          ›
        </button>
      </div>

      {week.data && (
        <div className="pad">
          <div className="gridcap">
            <span className="eyebrow">{week.data.team.name}</span>
            <span className="meta">
              {week.data.team.member_count}{" "}
              {week.data.team.member_count === 1 ? "person" : "people"}
            </span>
          </div>
          <div className="grid" role="table" aria-label={`${week.data.team.name} week`}>
            <div className="grid__head" role="row">
              {/* Empty corner. The team name is a caption above the grid --
                  inside the header it competes with Monday for the same
                  74 pixels and loses. */}
              <span className="grid__name" role="columnheader" />
              {week.data.days.map((d, i) => {
                const anchor = week.data!.anchor_days.includes(isoWeekday(d));
                return (
                  <span
                    key={d}
                    role="columnheader"
                    className={
                      "grid__day" +
                      (anchor ? " grid__day--anchor" : "") +
                      (d === todayIso ? " grid__day--today" : "")
                    }
                  >
                    <span className="grid__dow">{DOW[i]}</span>
                    <span className="grid__dom tabular">{Number(d.slice(8))}</span>
                  </span>
                );
              })}
            </div>

            {week.data.rows.map((row) => (
              <button
                key={row.user_id}
                className="grid__row"
                role="row"
                onClick={() => onOpenPerson(row.user_id)}
              >
                <span className="grid__name" role="cell">
                  <Avatar id={row.user_id} name={row.display_name} you={row.is_you} size={28} />
                  <span className="grid__who">
                    {row.is_you ? "You" : row.display_name.split(" ")[0]}
                  </span>
                </span>
                {row.cells.map((cell) => (
                  <span
                    key={cell.date}
                    role="cell"
                    className={`grid__cell grid__cell--${cell.kind}`}
                    aria-label={`${row.display_name}, ${cell.date}: ${CELL_LABEL[cell.kind]}`}
                  />
                ))}
              </button>
            ))}

            <div className="grid__foot" role="row">
              <span className="grid__name" role="cell">
                <span className="meta">In</span>
              </span>
              {week.data.in_per_day.map((n, i) => (
                <span key={i} role="cell" className="grid__total tabular">
                  {n || "·"}
                </span>
              ))}
            </div>
          </div>

          <Legend anchors={week.data.anchor_days.length > 0} />
        </div>
      )}
    </>
  );
}

function Legend({ anchors }: { anchors: boolean }) {
  return (
    <p className="legend">
      <span className="legend__item">
        <span className="grid__cell grid__cell--office" /> In
      </span>
      <span className="legend__item">
        <span className="grid__cell grid__cell--remote" /> Remote
      </span>
      <span className="legend__item">
        <span className="grid__cell grid__cell--leave" /> Away
      </span>
      {anchors && <span className="legend__item legend__item--anchor">Anchor day</span>}
    </p>
  );
}
