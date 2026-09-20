/**
 * One day at one office: who is booked where, and the desks that are out of
 * service. FR-8.6.
 *
 * ONE DAY, ONE SITE, ON PURPOSE. This is not privacy-filtered -- an admin
 * overriding a booking has to be able to see it -- and the shape is what
 * keeps that from becoming something else. A date range over one person is
 * an attendance record, which FR-9.5 rules out as a product position; a
 * single day at a single office is the operational view a workplace manager
 * actually works from.
 */

import { useState } from "react";

import { useCancelBooking, useFloor, useFloors, useSites } from "../api/hooks";
import {
  useAdminBookings,
  useReturnToService,
  useTakeOutOfService,
} from "../api/adminHooks";
import { Confirm, Empty, Field, Problem, Tag } from "./bits";

export function DaySection({ siteIds }: { siteIds: string[] | null }) {
  const sites = useSites(true);
  const all = sites.data ?? [];
  const mine = siteIds === null ? all : all.filter((s) => siteIds.includes(s.id));

  const [siteId, setSiteId] = useState("");
  const [on, setOn] = useState(() => new Date().toISOString().slice(0, 10));
  const site = mine.find((s) => s.id === siteId) ?? mine[0];

  const bookings = useAdminBookings(on, site?.id ?? "", Boolean(site));

  if (!site) return <Empty>No offices to show.</Empty>;

  return (
    <div className="stack">
      <div className="admin-inline">
        {mine.length > 1 && (
          <Field label="Office">
            <select
              className="admin-input"
              value={site.id}
              onChange={(e) => setSiteId(e.target.value)}
            >
              {mine.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Day">
          <input
            className="admin-input"
            type="date"
            value={on}
            onChange={(e) => setOn(e.target.value)}
          />
        </Field>
      </div>

      <section className="admin-sub">
        <span className="eyebrow">Booked that day</span>
        {bookings.isLoading && <p className="meta">Loading…</p>}
        {bookings.data?.length === 0 && <Empty>Nobody is booked at {site.name} that day.</Empty>}
        {bookings.data?.map((b) => (
          <BookingRow key={b.id} booking={b} on={on} />
        ))}
      </section>

      <OutOfServicePanel siteId={site.id} on={on} />
    </div>
  );
}

function BookingRow({
  booking,
  on,
}: {
  booking: {
    id: string;
    user_name: string;
    resource_name: string;
    booked_by: string | null;
  };
  on: string;
}) {
  const cancel = useCancelBooking();

  return (
    <div className="admin-row">
      <div className="admin-row__main">
        <span>
          <strong>{booking.resource_name}</strong>
          <span className="meta"> · {booking.user_name}</span>
          {/* Shown only when somebody else made it, because that is the only
              time it tells the reader anything. */}
          {booking.booked_by && <span className="meta"> · booked by {booking.booked_by}</span>}
        </span>
        <Confirm
          label="Release"
          consequence={`Release ${booking.resource_name} from ${booking.user_name} on ${on}? They are not notified — there is no notification service yet.`}
          busy={cancel.isPending}
          onConfirm={() => cancel.mutate({ bookingId: booking.id, on, floorId: "" })}
        />
      </div>
      <Problem error={cancel.error} />
    </div>
  );
}

/**
 * Taking a desk out of service, from the floor it is on.
 *
 * The desk list comes from the floor endpoint the employee app already uses,
 * rather than a new admin one: the thing an admin is looking for is the desk
 * with the broken monitor arm, and it is easier to find in the same order it
 * appears everywhere else.
 */
function OutOfServicePanel({ siteId, on }: { siteId: string; on: string }) {
  const floors = useFloors(siteId, on);
  const [floorId, setFloorId] = useState<string | null>(null);
  const picked = floorId && floors.data?.some((f) => f.id === floorId) ? floorId : floors.data?.[0]?.id;
  const floor = useFloor(picked);

  const out = useTakeOutOfService();
  const back = useReturnToService();
  const [target, setTarget] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [alsoRelease, setAlsoRelease] = useState(false);

  const resources = floor.data?.resources ?? [];
  const broken = resources.filter((r) => r.status === "out_of_service");

  return (
    <section className="admin-sub">
      <span className="eyebrow">Out of service</span>

      {broken.length === 0 && <Empty>Every desk on this floor is in service.</Empty>}
      {broken.map((r) => (
        <div key={r.id} className="admin-row">
          <div className="admin-row__main">
            <span>
              <strong>{r.name}</strong> <Tag tone="warn">Out of service</Tag>
            </span>
            <button
              className="btn btn--quiet"
              disabled={back.isPending}
              onClick={() => back.mutate(r.id)}
            >
              Return to service
            </button>
          </div>
        </div>
      ))}

      {(floors.data?.length ?? 0) > 1 && (
        <Field label="Floor">
          <select
            className="admin-input"
            value={picked ?? ""}
            onChange={(e) => setFloorId(e.target.value)}
          >
            {floors.data?.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </Field>
      )}

      <Field label="Take a desk out of service">
        <select
          className="admin-input"
          value={target ?? ""}
          onChange={(e) => setTarget(e.target.value || null)}
        >
          <option value="">Choose a desk…</option>
          {resources
            .filter((r) => r.status === "active")
            .map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
        </select>
      </Field>

      {target && (
        <div className="admin-form">
          <Field
            label="Reason"
            hint="Employees see this on the desk. “Out of service” with no reason generates a support ticket per desk per day."
          >
            <input
              className="admin-input"
              value={reason}
              placeholder="Monitor arm snapped"
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          <label className="admin-check">
            <input
              type="checkbox"
              checked={alsoRelease}
              onChange={(e) => setAlsoRelease(e.target.checked)}
            />
            <span>
              Also release bookings already on it
              <span className="admin-field__hint">
                Off by default. A desk going out of service next Monday should not evict
                whoever is sitting at it today.
              </span>
            </span>
          </label>
          <Problem error={out.error} />
          <button
            className="btn btn--primary"
            disabled={reason.trim().length < 3 || out.isPending}
            onClick={() =>
              out.mutate(
                { resourceId: target, reason: reason.trim(), releaseBookings: alsoRelease },
                {
                  onSuccess: () => {
                    setTarget(null);
                    setReason("");
                    setAlsoRelease(false);
                  },
                },
              )
            }
          >
            {out.isPending ? "Working…" : "Take out of service"}
          </button>
        </div>
      )}
      <Problem error={back.error} />
    </section>
  );
}
