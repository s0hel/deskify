import { useState } from "react";

import { useMe, useSetVisibility, type Visibility } from "../api/hooks";
import { Sheet } from "../ui/Sheet";
import { Chevron } from "../ui/bits";
import { Avatar } from "./Avatar";
import { HomeSiteSheet } from "./HomeSiteSheet";

/**
 * FR-5.6, presented as the reference does: the setting is described by what it
 * means for the person, not by its enum value.
 */
const OPTIONS: { value: Visibility; label: string; detail: string }[] = [
  {
    value: "everyone",
    label: "Everyone",
    detail: "Anyone at your company can see the days you're in and where you sit.",
  },
  {
    value: "team",
    label: "My teams only",
    detail: "Only people in a group with you. Everyone else won't see you at all.",
  },
  {
    value: "nobody",
    label: "Nobody",
    detail:
      "You won't appear in anyone's team view or on the plan. You can still book as normal.",
  },
];

export function MeScreen({
  onSignOut,
  onOpenAdmin,
}: {
  onSignOut: () => void;
  /** The console replaces the whole screen, including the app's own topbar
   *  and tab bar, so App owns it -- the same way it owns PersonScreen. */
  onOpenAdmin: () => void;
}) {
  const me = useMe(true);
  const setVisibility = useSetVisibility();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [officeOpen, setOfficeOpen] = useState(false);

  if (!me.data) {
    return (
      <div className="scroll pad">
        <p className="meta">Loading…</p>
      </div>
    );
  }

  const current = OPTIONS.find((o) => o.value === me.data.presence_visibility);

  return (
    <div className="scroll">
      <div className="pad person-head">
        <Avatar id={me.data.user_id} name={me.data.display_name} you size={56} />
        <div>
          <h2 className="title">{me.data.display_name}</h2>
          <p className="meta">{me.data.email}</p>
        </div>
      </div>

      <section className="section pad">
        <span className="eyebrow">Office</span>
        <button className="row-card" onClick={() => setOfficeOpen(true)}>
          <span>
            <span className="person__name">Your usual office</span>
            <br />
            <span className="meta">
              {me.data.home_site?.name ?? "Not set"}
              {me.data.home_site && me.data.home_site_id === null && " · not chosen yet"}
            </span>
          </span>
          <Chevron />
        </button>
      </section>

      <section className="section pad">
        <span className="eyebrow">Presence</span>
        <button className="row-card" onClick={() => setSheetOpen(true)}>
          <span>
            <span className="person__name">Who can see your days</span>
            <br />
            <span className="meta">{current?.label}</span>
          </span>
          <Chevron />
        </button>
      </section>

      <section className="section pad">
        <span className="eyebrow">Account</span>
        <div className="card kv">
          <Row label="Teams" value={me.data.teams.join(", ") || "None"} />
          <Row label="Locale" value={me.data.locale} />
          <Row label="Organization" value={me.data.organization_id.slice(0, 8)} />
        </div>
      </section>

      {/* FR-1.8. The door exists only for someone who holds a grant. It is
          not the permission -- every admin endpoint re-checks server-side --
          but an employee should not be shown a room they cannot enter. */}
      {me.data.is_admin && (
        <section className="section pad">
          <span className="eyebrow">Workplace</span>
          <button className="row-card" onClick={onOpenAdmin}>
            <span>
              <span className="person__name">Admin console</span>
              <br />
              <span className="meta">
                {me.data.administered_site_ids === null
                  ? "Every office, people and permissions"
                  : `${me.data.administered_site_ids.length} office${
                      me.data.administered_site_ids.length === 1 ? "" : "s"
                    }`}
              </span>
            </span>
            <Chevron />
          </button>
        </section>
      )}

      <div className="pad section">
        <button className="btn btn--quiet btn--danger-text" onClick={onSignOut}>
          Sign out
        </button>
      </div>
      <div style={{ height: 24 }} />

      {officeOpen && (
        <HomeSiteSheet
          currentSiteId={me.data.home_site?.id ?? null}
          onClose={() => setOfficeOpen(false)}
        />
      )}

      {sheetOpen && (
        <Sheet open onClose={() => setSheetOpen(false)} labelledBy="visibility-title">
          <h2 className="title" id="visibility-title">
            Who can see your days
          </h2>
          <div className="stack" style={{ marginTop: 14 }}>
            {OPTIONS.map((o) => {
              const chosen = o.value === me.data!.presence_visibility;
              return (
                <button
                  key={o.value}
                  className={chosen ? "choice choice--on" : "choice"}
                  aria-pressed={chosen}
                  disabled={setVisibility.isPending}
                  onClick={() =>
                    setVisibility.mutate(o.value, { onSuccess: () => setSheetOpen(false) })
                  }
                >
                  <span className="choice__label">{o.label}</span>
                  <span className="choice__detail">{o.detail}</span>
                  {chosen && (
                    <span className="choice__tick" aria-hidden="true">
                      ✓
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </Sheet>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="kv__row">
      <span className="meta">{label}</span>
      <span className="kv__value tabular">{value}</span>
    </div>
  );
}
