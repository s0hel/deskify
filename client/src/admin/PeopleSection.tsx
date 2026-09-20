/**
 * The directory: people, roles and groups. FR-8.4, FR-1.8.
 *
 * Org admins only, and the console does not render the tab for anyone else
 * rather than showing one that refuses — a control that is always going to
 * say no is worse than no control.
 *
 * This screen lists everyone regardless of their presence setting, which is
 * the one deliberate exception to FR-5.6: privacy governs what COLLEAGUES may
 * learn about each other, and it was never a claim that the employer does not
 * know who works there. What it must not become is a way around that setting,
 * so the payload the API returns carries a count of upcoming bookings and
 * never which desk on which day.
 */

import { useState } from "react";

import { useSites } from "../api/hooks";
import {
  useAdminGroups,
  useAdminUsers,
  useCreateUser,
  useDeactivateUser,
  useReactivateUser,
  useSetUserRoles,
  useUpdateGroup,
  type AdminUser,
  type RoleName,
} from "../api/adminHooks";
import { Confirm, Empty, Field, Problem, Tag } from "./bits";

const ROLE_LABELS: Record<RoleName, string> = {
  org_admin: "Organization admin",
  site_admin: "Site admin",
  team_lead: "Team lead",
};

export function PeopleSection({ myUserId }: { myUserId: string }) {
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const users = useAdminUsers(q, true);
  const sites = useSites(true);
  const groups = useAdminGroups(true);

  return (
    <div className="stack">
      <input
        className="admin-input"
        placeholder="Search by name or email"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Search people"
      />

      {users.isLoading && <p className="meta">Loading…</p>}
      {users.data?.length === 0 && <Empty>Nobody matches “{q}”.</Empty>}

      {users.data?.map((user) => (
        <div key={user.id} className="admin-card">
          <button
            className="admin-card__head"
            aria-expanded={selected === user.id}
            onClick={() => setSelected(selected === user.id ? null : user.id)}
          >
            <span>
              <span className="admin-card__title">
                {user.display_name}
                {user.id === myUserId && <span className="meta"> · you</span>}
              </span>
              <span className="meta">{user.email}</span>
            </span>
            <span className="admin-card__tags">
              {user.status === "deactivated" && <Tag tone="warn">Deactivated</Tag>}
              {user.roles.map((r) => (
                <Tag key={`${r.role}-${r.scope_id}`}>
                  {r.role === "org_admin" ? "Org admin" : r.scope_name ?? ROLE_LABELS[r.role]}
                </Tag>
              ))}
            </span>
          </button>

          {selected === user.id && (
            <div className="admin-card__body">
              <PersonDetail
                user={user}
                isMe={user.id === myUserId}
                sites={sites.data ?? []}
              />
            </div>
          )}
        </div>
      ))}

      {adding ? (
        <NewPersonForm sites={sites.data ?? []} onDone={() => setAdding(false)} />
      ) : (
        <button className="btn btn--quiet" onClick={() => setAdding(true)}>
          Add a person
        </button>
      )}

      <section className="admin-sub">
        <span className="eyebrow">Teams</span>
        {groups.data?.map((g) => (
          <GroupRow key={g.id} group={g} />
        ))}
      </section>
    </div>
  );
}

function PersonDetail({
  user,
  isMe,
  sites,
}: {
  user: AdminUser;
  isMe: boolean;
  sites: { id: string; name: string }[];
}) {
  const setRoles = useSetUserRoles();
  const deactivate = useDeactivateUser();
  const reactivate = useReactivateUser();

  const isOrgAdmin = user.roles.some((r) => r.role === "org_admin");
  const adminSites = new Set(
    user.roles.filter((r) => r.role === "site_admin").map((r) => r.scope_id),
  );

  /** Roles are replaced wholesale, so every toggle sends the full set. That
   *  keeps the screen and the rows behind it from drifting. */
  function submit(next: { role: RoleName; scope_id?: string | null }[]) {
    setRoles.mutate({ userId: user.id, roles: next });
  }

  function toggleOrgAdmin(on: boolean) {
    const keep = user.roles
      .filter((r) => r.role !== "org_admin")
      .map((r) => ({ role: r.role, scope_id: r.scope_id }));
    submit(on ? [...keep, { role: "org_admin" }] : keep);
  }

  function toggleSite(siteId: string, on: boolean) {
    const others = user.roles
      .filter((r) => !(r.role === "site_admin" && r.scope_id === siteId))
      .map((r) => ({ role: r.role, scope_id: r.scope_id }));
    submit(on ? [...others, { role: "site_admin", scope_id: siteId }] : others);
  }

  return (
    <div className="admin-form">
      <div className="kv">
        <div className="kv__row">
          <span className="meta">Teams</span>
          <span className="kv__value">{user.teams.join(", ") || "None"}</span>
        </div>
        <div className="kv__row">
          <span className="meta">Upcoming bookings</span>
          <span className="kv__value tabular">{user.future_bookings}</span>
        </div>
      </div>

      <span className="eyebrow">Permissions</span>
      <label className="admin-check">
        <input
          type="checkbox"
          checked={isOrgAdmin}
          disabled={setRoles.isPending}
          onChange={(e) => toggleOrgAdmin(e.target.checked)}
        />
        <span>
          Organization admin
          <span className="admin-field__hint">
            Every office, plus people and permissions. The last one cannot be removed.
          </span>
        </span>
      </label>

      <span className="admin-field__label">Site admin for</span>
      <div className="chiprow">
        {sites.map((s) => {
          const on = adminSites.has(s.id);
          return (
            <button
              key={s.id}
              className={on ? "chip chip--on" : "chip"}
              aria-pressed={on}
              disabled={setRoles.isPending || isOrgAdmin}
              onClick={() => toggleSite(s.id, !on)}
            >
              {s.name}
            </button>
          );
        })}
      </div>
      {isOrgAdmin && (
        <p className="admin-field__hint">
          An organization admin already administers every office, so per-site grants would
          add nothing.
        </p>
      )}

      <Problem error={setRoles.error || deactivate.error || reactivate.error} />

      {user.status === "active" ? (
        isMe ? (
          <p className="admin-field__hint">
            You cannot deactivate your own account — ask another administrator.
          </p>
        ) : (
          <Confirm
            label={`Deactivate ${user.display_name}`}
            consequence={
              user.future_bookings > 0
                ? `This releases ${user.future_bookings} upcoming desk${
                    user.future_bookings === 1 ? "" : "s"
                  } back to the pool and signs them out. Past bookings are kept.`
                : "They keep their history and stop being able to sign in. Nothing is deleted."
            }
            busy={deactivate.isPending}
            onConfirm={() => deactivate.mutate(user.id)}
          />
        )
      ) : (
        <div>
          <p className="admin-field__hint">
            Their released desks were not held. Someone else may be sitting at them.
          </p>
          <button
            className="btn btn--quiet"
            disabled={reactivate.isPending}
            onClick={() => reactivate.mutate(user.id)}
          >
            Reactivate
          </button>
        </div>
      )}
    </div>
  );
}

function NewPersonForm({
  sites,
  onDone,
}: {
  sites: { id: string; name: string }[];
  onDone: () => void;
}) {
  const create = useCreateUser();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [home, setHome] = useState("");

  return (
    <div className="admin-card admin-card__body">
      <h3 className="admin-card__title">Add a person</h3>
      <div className="admin-form">
        <Field label="Email">
          <input
            className="admin-input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="Name">
          <input className="admin-input" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Usual office" hint="They can change this themselves, and book anywhere regardless.">
          <select className="admin-input" value={home} onChange={(e) => setHome(e.target.value)}>
            <option value="">Not set</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Problem error={create.error} />
        <div className="admin-confirm__row">
          <button
            className="btn btn--primary"
            disabled={!email.trim() || !name.trim() || create.isPending}
            onClick={() =>
              create.mutate(
                {
                  email: email.trim(),
                  display_name: name.trim(),
                  home_site_id: home || null,
                },
                { onSuccess: onDone },
              )
            }
          >
            {create.isPending ? "Adding…" : "Add person"}
          </button>
          <button className="btn btn--quiet" onClick={onDone}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function GroupRow({
  group,
}: {
  group: { id: string; name: string; member_count: number; anchor_days: number[] };
}) {
  const update = useUpdateGroup();

  /** FR-5.4/5.8. ISO weekdays, 1 = Monday — the same numbering the team grid
   *  reads, so a day set here lands on the column an employee expects. */
  function toggle(day: number) {
    const next = group.anchor_days.includes(day)
      ? group.anchor_days.filter((d) => d !== day)
      : [...group.anchor_days, day];
    update.mutate({ groupId: group.id, patch: { anchor_days: next } });
  }

  return (
    <div className="admin-row">
      <div className="admin-row__main">
        <span>
          {group.name} <span className="meta">· {group.member_count} people</span>
        </span>
      </div>
      <div className="chiprow">
        {WEEKDAYS.slice(0, 5).map((label, i) => {
          const day = i + 1;
          const on = group.anchor_days.includes(day);
          return (
            <button
              key={day}
              className={on ? "chip chip--on" : "chip"}
              aria-pressed={on}
              disabled={update.isPending}
              onClick={() => toggle(day)}
            >
              {label}
            </button>
          );
        })}
      </div>
      <Problem error={update.error} />
    </div>
  );
}
