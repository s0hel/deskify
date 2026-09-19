import { Suspense, lazy, useState } from "react";

import { useMe, useSetVisibility, type Visibility } from "../api/hooks";
import { Sheet } from "../ui/Sheet";
import { Chevron } from "../ui/bits";
import { Avatar } from "./Avatar";

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

// Lazily loaded, so the admin bundle never sits in the employee cold-start
// path (TDD §10.1).
const AdminConsole = lazy(() => import("../admin/AdminConsole"));

export function MeScreen({ onSignOut }: { onSignOut: () => void }) {
  const me = useMe(true);
  const setVisibility = useSetVisibility();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);

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

      <section className="section pad">
        <span className="eyebrow">Workplace</span>
        {adminOpen ? (
          <div className="card">
            <Suspense fallback={<p className="meta">Loading console…</p>}>
              <AdminConsole />
            </Suspense>
            <button
              className="btn btn--quiet"
              style={{ marginTop: 14 }}
              onClick={() => setAdminOpen(false)}
            >
              Close
            </button>
          </div>
        ) : (
          <button className="row-card" onClick={() => setAdminOpen(true)}>
            <span className="person__name">Admin console</span>
            <Chevron />
          </button>
        )}
      </section>

      <div className="pad section">
        <button className="btn btn--quiet btn--danger-text" onClick={onSignOut}>
          Sign out
        </button>
      </div>
      <div style={{ height: 24 }} />

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
