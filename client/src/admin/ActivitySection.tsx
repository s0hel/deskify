/**
 * The audit log. FR-8.8.
 *
 * Read-only by construction -- there is no endpoint that edits or deletes an
 * entry, and adding one would defeat the table.
 *
 * Each row is rendered from `action` plus the before/after the server
 * recorded, rather than from a sentence the server wrote. Two reasons: the
 * strings have to translate (FR-10.4) like every other one in the app, and a
 * log whose text is baked in at write time cannot be improved for entries
 * that already exist.
 */

import { useAudit, type AuditEntry } from "../api/adminHooks";
import { Empty } from "./bits";

const ACTIONS: Record<string, string> = {
  "site.create": "created an office",
  "site.update": "changed an office",
  "floor.create": "added a floor",
  "floor.update": "renamed a floor",
  "zone.create": "added a zone",
  "zone.update": "changed a zone",
  "zone.delete": "deleted a zone",
  "user.create": "added a person",
  "user.update": "changed a person",
  "user.roles": "changed permissions",
  "user.deactivate": "deactivated a person",
  "user.reactivate": "reactivated a person",
  "group.create": "created a team",
  "group.update": "changed a team",
  "group.members": "changed team membership",
  "resource.out_of_service": "took a desk out of service",
  "resource.in_service": "returned a desk to service",
  "booking.create_for": "booked a desk for someone",
};

export function ActivitySection() {
  const audit = useAudit(true);

  if (audit.isLoading) return <p className="meta">Loading…</p>;
  if (!audit.data?.length) return <Empty>Nothing has been changed yet.</Empty>;

  return (
    <ol className="admin-audit">
      {audit.data.map((entry) => (
        <li key={entry.id}>
          <div className="admin-audit__line">
            <strong>{entry.actor_name ?? "Someone"}</strong>{" "}
            {ACTIONS[entry.action] ?? entry.action}
            <span className="meta"> · {when(entry.at)}</span>
          </div>
          <Detail entry={entry} />
        </li>
      ))}
    </ol>
  );
}

/**
 * The before value is the point.
 *
 * "Site updated" is almost useless six months later; "cap 120 → 60" is the
 * answer to the question someone is actually asking when they open this.
 */
function Detail({ entry }: { entry: AuditEntry }) {
  const { before, after, ...rest } = entry.detail as Record<string, unknown>;

  const changes =
    before && after && typeof before === "object" && typeof after === "object"
      ? Object.keys(after as object).map((key) => ({
          key,
          from: (before as Record<string, unknown>)[key],
          to: (after as Record<string, unknown>)[key],
        }))
      : [];

  const extras = Object.entries(rest).filter(([, v]) => v !== null && v !== "" && v !== false);

  if (changes.length === 0 && extras.length === 0) return null;

  return (
    <ul className="admin-audit__detail">
      {changes.map(({ key, from, to }) => (
        <li key={key}>
          <span className="meta">{label(key)}</span> {show(from)} → {show(to)}
        </li>
      ))}
      {extras.map(([key, value]) => (
        <li key={key}>
          <span className="meta">{label(key)}</span> {show(value)}
        </li>
      ))}
    </ul>
  );
}

function label(key: string): string {
  return key.replace(/_/g, " ");
}

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.length ? value.map(show).join(", ") : "none";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Relative for anything recent, absolute once it stops being "ago". */
function when(iso: string): string {
  const then = new Date(iso);
  const minutes = Math.round((Date.now() - then.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)}h ago`;
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
