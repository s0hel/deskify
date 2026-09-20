/**
 * Admin console entry point. Lazily loaded (TDD §10.1), so none of this sits
 * in the employee cold-start path.
 *
 * THE TABS FOLLOW THE CALLER'S GRANTS. A site admin administers one office:
 * they get Offices and Today, and People and Activity are not rendered at
 * all rather than rendered and refusing. A tab that is always going to
 * answer 403 is worse than no tab, because the only way to find that out is
 * to press it.
 *
 * None of this is the permission. `/me` says whether to offer the console and
 * which sites to scope it to, and every endpoint re-checks the grants
 * server-side -- a client that shows a button is not a client that may press
 * it. The tests that hold that line are api/tests/test_admin.py.
 *
 * NOT HERE YET: the floor-plan editor (FR-8.2 -- the same FloorPlan component
 * with `editable`, plus bulk placement and zone drawing), CSV import
 * (FR-8.3), the policy editor (FR-8.5) and QR label sheets (FR-8.7).
 */

import { useState } from "react";

import { useMe } from "../api/hooks";
import { ActivitySection } from "./ActivitySection";
import { DaySection } from "./DaySection";
import { OfficesSection } from "./OfficesSection";
import { PeopleSection } from "./PeopleSection";

type Section = "offices" | "day" | "people" | "activity";

export default function AdminConsole({ onClose }: { onClose?: () => void }) {
  const me = useMe(true);
  const [section, setSection] = useState<Section>("offices");

  if (!me.data) return <p className="meta">Loading…</p>;

  // `administered_site_ids` is null for an org admin, meaning every office --
  // not a list that would have to be recomputed the day someone adds one.
  const orgWide = me.data.administered_site_ids === null;
  const tabs: { id: Section; label: string }[] = [
    { id: "offices", label: "Offices" },
    { id: "day", label: "Today" },
    ...(orgWide
      ? ([
          { id: "people", label: "People" },
          { id: "activity", label: "Activity" },
        ] as const)
      : []),
  ];

  return (
    <div className="admin">
      <header className="admin__head">
        <div>
          <span className="eyebrow">Workplace admin</span>
          <h1 className="title">
            {orgWide ? "Your organization" : "Your office"}
          </h1>
        </div>
        {onClose && (
          <button className="btn btn--quiet admin__close" onClick={onClose}>
            Done
          </button>
        )}
      </header>

      <nav className="admin__tabs" aria-label="Admin sections">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={section === t.id ? "chip chip--on" : "chip"}
            aria-pressed={section === t.id}
            onClick={() => setSection(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="admin__body">
        {section === "offices" && <OfficesSection canCreateSites={orgWide} />}
        {section === "day" && <DaySection siteIds={me.data.administered_site_ids} />}
        {section === "people" && orgWide && <PeopleSection myUserId={me.data.user_id} />}
        {section === "activity" && orgWide && <ActivitySection />}
      </div>
    </div>
  );
}
