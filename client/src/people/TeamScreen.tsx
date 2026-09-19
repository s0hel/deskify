import { useMemo, useState } from "react";

import { usePeople, type DayAvailability, type Person } from "../api/hooks";
import { WeekStrip } from "../booking/WeekStrip";
import { Chevron } from "../ui/bits";
import { Avatar } from "./Avatar";
import { WeekGrid } from "./WeekGrid";

/**
 * FR-5.1 and FR-5.4 -- who is in, grouped so your own team reads first.
 *
 * The list is what the server chose to show you. A colleague set to `nobody`
 * is not here and is not counted, because the filter runs in the query rather
 * than on the way out (TDD §5.2) -- so this screen cannot accidentally reveal
 * that someone exists but is hidden.
 */
export function TeamScreen({
  days,
  selected,
  todayIso,
  onPickDay,
  onOpenPerson,
}: {
  days: DayAvailability[];
  selected: string;
  todayIso: string;
  onPickDay: (iso: string) => void;
  onOpenPerson: (userId: string) => void;
}) {
  const [view, setView] = useState<"day" | "week">("day");
  const [query, setQuery] = useState("");
  const people = usePeople(selected, view === "day");

  const { mine, others, away } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = (p: Person) => !q || p.display_name.toLowerCase().includes(q);
    const inOffice = (people.data?.in_office ?? []).filter(match);
    return {
      mine: inOffice.filter((p) => p.shared_teams.length > 0 || p.is_you),
      others: inOffice.filter((p) => p.shared_teams.length === 0 && !p.is_you),
      away: (people.data?.away ?? []).filter(match),
    };
  }, [people.data, query]);

  const total = mine.length + others.length;

  return (
    <div className="scroll">
      <div className="pad" style={{ marginBottom: 12 }}>
        <div className="seg seg--flush">
          <button aria-pressed={view === "day"} onClick={() => setView("day")}>
            Who's in
          </button>
          <button aria-pressed={view === "week"} onClick={() => setView("week")}>
            Week
          </button>
        </div>
      </div>

      {view === "week" ? (
        <>
          <WeekGrid todayIso={todayIso} onOpenPerson={onOpenPerson} />
          <div style={{ height: 24 }} />
        </>
      ) : (
        <DayView
          days={days}
          selected={selected}
          todayIso={todayIso}
          onPickDay={onPickDay}
          onOpenPerson={onOpenPerson}
          query={query}
          setQuery={setQuery}
          loading={people.isLoading}
          mine={mine}
          others={others}
          away={away}
          total={total}
        />
      )}
    </div>
  );
}

function DayView({
  days,
  selected,
  todayIso,
  onPickDay,
  onOpenPerson,
  query,
  setQuery,
  loading,
  mine,
  others,
  away,
  total,
}: {
  days: DayAvailability[];
  selected: string;
  todayIso: string;
  onPickDay: (iso: string) => void;
  onOpenPerson: (userId: string) => void;
  query: string;
  setQuery: (q: string) => void;
  loading: boolean;
  mine: Person[];
  others: Person[];
  away: Person[];
  total: number;
}) {
  return (
    <>
      <div className="pad">
        <input
          className="search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find a colleague"
          aria-label="Find a colleague"
        />
      </div>

      <WeekStrip days={days} selected={selected} todayIso={todayIso} onPick={onPickDay} />

      <p className="meta pad" style={{ marginTop: 10 }}>
        {loading
          ? "Loading…"
          : total === 0
            ? "Nobody has booked a desk yet."
            : `${total} ${total === 1 ? "person" : "people"} in`}
      </p>

      {mine.length > 0 && (
        <Group
          title={mine[0]?.shared_teams[0] ?? "Your team"}
          people={mine}
          onOpen={onOpenPerson}
        />
      )}
      {others.length > 0 && (
        <Group title="Also in the office" people={others} onOpen={onOpenPerson} />
      )}
      {away.length > 0 && <Group title="Away" people={away} onOpen={onOpenPerson} />}

      <div style={{ height: 24 }} />
    </>
  );
}

const AWAY_LABEL: Record<string, string> = {
  remote: "Working remotely",
  leave: "On leave",
};

function Group({
  title,
  people,
  onOpen,
}: {
  title: string;
  people: Person[];
  onOpen: (id: string) => void;
}) {
  return (
    <section className="section pad">
      <span className="eyebrow">{title}</span>
      <div className="stack">
        {people.map((p) => (
          <button
            key={p.user_id}
            className="row-card"
            onClick={() => onOpen(p.user_id)}
            aria-label={`${p.display_name}${p.is_you ? ", you" : ""}. ${
              p.declaration ? AWAY_LABEL[p.declaration] : `${p.resource_name}, ${p.floor_name}`
            }`}
          >
            <span className="person">
              <Avatar id={p.user_id} name={p.display_name} you={p.is_you} />
              <span>
                <span className="person__name">
                  {p.display_name}
                  {p.is_you && <span className="muted-inline"> You</span>}
                </span>
                <br />
                <span className="meta tabular">
                  {p.declaration
                    ? AWAY_LABEL[p.declaration]
                    : [p.resource_name, p.floor_name].filter(Boolean).join(" · ")}
                </span>
              </span>
            </span>
            <Chevron />
          </button>
        ))}
      </div>
    </section>
  );
}
