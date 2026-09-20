/**
 * Offices, floors and zones. FR-8.1.
 *
 * The screen is organised the way the data is: a site contains floors, a
 * floor contains zones. A site admin sees only the offices they administer,
 * which the API has already filtered -- the client does not decide that, it
 * only renders what came back.
 */

import { useState } from "react";

import { useSites } from "../api/hooks";
import {
  useAdminFloors,
  useAdminZones,
  useCreateFloor,
  useCreateSite,
  useDeleteZone,
  useUpdateFloor,
  useUpdateSite,
  type AdminFloor,
} from "../api/adminHooks";
import { Confirm, Empty, Field, Problem, Tag } from "./bits";

export function OfficesSection({ canCreateSites }: { canCreateSites: boolean }) {
  const sites = useSites(true);
  const floors = useAdminFloors();
  const zones = useAdminZones();
  const [openSite, setOpenSite] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  if (sites.isLoading || floors.isLoading) return <p className="meta">Loading…</p>;

  const visible = (sites.data ?? []).filter(
    (s) => floors.data?.some((f) => f.site_id === s.id) || canCreateSites,
  );

  return (
    <div className="stack">
      {visible.length === 0 && <Empty>No offices yet.</Empty>}

      {visible.map((site) => {
        const open = openSite === site.id;
        const mine = (floors.data ?? []).filter((f) => f.site_id === site.id);
        const desks = mine.reduce((n, f) => n + f.desk_count, 0);
        return (
          <div key={site.id} className="admin-card">
            <button
              className="admin-card__head"
              aria-expanded={open}
              onClick={() => setOpenSite(open ? null : site.id)}
            >
              <span>
                <span className="admin-card__title">{site.name}</span>
                <span className="meta">
                  {site.timezone} · {mine.length} floor{mine.length === 1 ? "" : "s"} ·{" "}
                  {desks} desk{desks === 1 ? "" : "s"}
                </span>
              </span>
              <span className="admin-card__mark" aria-hidden="true">
                {open ? "–" : "+"}
              </span>
            </button>

            {open && (
              <div className="admin-card__body">
                <SiteForm site={site} />
                <FloorList
                  siteId={site.id}
                  floors={mine}
                  zones={zones.data ?? []}
                />
              </div>
            )}
          </div>
        );
      })}

      {canCreateSites &&
        (adding ? (
          <NewSiteForm onDone={() => setAdding(false)} />
        ) : (
          <button className="btn btn--quiet" onClick={() => setAdding(true)}>
            Add an office
          </button>
        ))}
    </div>
  );
}

function SiteForm({ site }: { site: { id: string; name: string; capacity_cap: number | null; check_in_enabled: boolean } }) {
  const update = useUpdateSite();
  const [name, setName] = useState(site.name);
  const [cap, setCap] = useState(site.capacity_cap?.toString() ?? "");

  const dirty = name !== site.name || cap !== (site.capacity_cap?.toString() ?? "");

  return (
    <div className="admin-form">
      <Field label="Name">
        <input className="admin-input" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field
        label="Daily cap"
        hint="Leave empty for no cap. A cap below the desk count is allowed and deliberate — it is how a site runs at reduced occupancy."
      >
        <input
          className="admin-input"
          inputMode="numeric"
          placeholder="No cap"
          value={cap}
          onChange={(e) => setCap(e.target.value.replace(/[^0-9]/g, ""))}
        />
      </Field>
      <label className="admin-check">
        <input
          type="checkbox"
          checked={site.check_in_enabled}
          onChange={(e) =>
            update.mutate({ siteId: site.id, patch: { check_in_enabled: e.target.checked } as never })
          }
        />
        {/* FR-4.7. Some works councils reject check-in outright, so this is a
            per-site switch rather than a product-wide assumption. */}
        <span>
          Check-in required
          <span className="admin-field__hint">
            Turn this off where check-in is not acceptable. Bookings are never auto-released
            at an office with it off.
          </span>
        </span>
      </label>

      {/* The timezone is absent on purpose: it is the day-boundary rule for
          every booking already recorded here, and changing it re-dates them.
          The API refuses it once bookings exist (TDD §3.5), and offering a
          control that usually fails is worse than not offering it. */}
      <p className="admin-field__hint">
        Timezone is fixed once bookings exist — a genuine move is a new office.
      </p>

      <Problem error={update.error} />
      <button
        className="btn btn--primary"
        disabled={!dirty || update.isPending}
        onClick={() =>
          update.mutate({
            siteId: site.id,
            patch: { name, capacity_cap: cap === "" ? null : Number(cap) } as never,
          })
        }
      >
        {update.isPending ? "Saving…" : "Save office"}
      </button>
    </div>
  );
}

function NewSiteForm({ onDone }: { onDone: () => void }) {
  const create = useCreateSite();
  const [name, setName] = useState("");
  // Defaulting to the browser's zone is right far more often than defaulting
  // to UTC, and it is the admin's own office in the common case.
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone);

  return (
    <div className="admin-card admin-card__body">
      <h3 className="admin-card__title">New office</h3>
      <div className="admin-form">
        <Field label="Name">
          <input
            className="admin-input"
            value={name}
            placeholder="Lisbon Alfama"
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="Timezone" hint="An IANA name, e.g. Europe/Lisbon. Everything at this office is shown in it.">
          <input className="admin-input" value={tz} onChange={(e) => setTz(e.target.value)} />
        </Field>
        <Problem error={create.error} />
        <div className="admin-confirm__row">
          <button
            className="btn btn--primary"
            disabled={!name.trim() || create.isPending}
            onClick={() =>
              create.mutate({ name: name.trim(), timezone: tz }, { onSuccess: onDone })
            }
          >
            {create.isPending ? "Creating…" : "Create office"}
          </button>
          <button className="btn btn--quiet" onClick={onDone}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function FloorList({
  siteId,
  floors,
  zones,
}: {
  siteId: string;
  floors: AdminFloor[];
  zones: { id: string; floor_id: string; name: string; resource_count: number }[];
}) {
  const create = useCreateFloor();
  const [name, setName] = useState("");

  return (
    <div className="admin-sub">
      <span className="eyebrow">Floors</span>
      {floors.length === 0 && <Empty>No floors yet.</Empty>}
      {floors.map((floor) => (
        <FloorRow key={floor.id} floor={floor} zones={zones.filter((z) => z.floor_id === floor.id)} />
      ))}

      <div className="admin-inline">
        <input
          className="admin-input"
          placeholder="Add a floor, e.g. 3F"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          className="btn btn--quiet"
          disabled={!name.trim() || create.isPending}
          onClick={() =>
            create.mutate(
              { site_id: siteId, name: name.trim(), ordinal: floors.length },
              { onSuccess: () => setName("") },
            )
          }
        >
          Add
        </button>
      </div>
      <Problem error={create.error} />
    </div>
  );
}

function FloorRow({
  floor,
  zones,
}: {
  floor: AdminFloor;
  zones: { id: string; name: string; resource_count: number }[];
}) {
  const update = useUpdateFloor();
  const remove = useDeleteZone();
  const [name, setName] = useState(floor.name);
  const [open, setOpen] = useState(false);

  return (
    <div className="admin-row">
      <div className="admin-row__main">
        <input
          className="admin-input admin-input--flush"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => name !== floor.name && name.trim() && update.mutate({ floorId: floor.id, patch: { name: name.trim() } })}
          aria-label={`Name of ${floor.name}`}
        />
        <span className="meta">
          {floor.desk_count === 0 ? (
            // An unfinished import should look unfinished. A floor with no
            // desks on it is the most common half-done state there is.
            <Tag tone="warn">No desks placed</Tag>
          ) : (
            `${floor.desk_count} desks`
          )}
          {floor.plan_asset_key === null && <Tag tone="quiet">No plan</Tag>}
        </span>
      </div>
      {zones.length > 0 && (
        <button className="admin-row__more" onClick={() => setOpen(!open)} aria-expanded={open}>
          {zones.length} zone{zones.length === 1 ? "" : "s"}
        </button>
      )}
      {open && (
        <ul className="admin-zonelist">
          {zones.map((z) => (
            <li key={z.id}>
              <span>
                {z.name} <span className="meta">· {z.resource_count} desks</span>
              </span>
              {z.resource_count === 0 && (
                <Confirm
                  label="Delete"
                  consequence={`Delete the zone “${z.name}”? It has no desks in it, so nothing else changes.`}
                  busy={remove.isPending}
                  onConfirm={() => remove.mutate(z.id)}
                />
              )}
            </li>
          ))}
        </ul>
      )}
      <Problem error={update.error || remove.error} />
    </div>
  );
}
