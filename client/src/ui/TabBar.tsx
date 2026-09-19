export type Tab = "today" | "spaces" | "team" | "me";

const TABS: { id: Tab; label: string; icon: JSX.Element }[] = [
  {
    id: "today",
    label: "Today",
    icon: (
      <path d="M3 10.5L12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
    ),
  },
  {
    id: "spaces",
    label: "Spaces",
    icon: <path d="M3 4h18v16H3zM3 9h18M9 9v11" />,
  },
  {
    id: "team",
    label: "Team",
    icon: (
      <>
        <circle cx="9" cy="8" r="3.2" />
        <path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5" />
        <path d="M16 6.2A3.2 3.2 0 0 1 16 14" />
      </>
    ),
  },
  {
    id: "me",
    label: "Me",
    icon: (
      <>
        <circle cx="12" cy="8" r="3.4" />
        <path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" />
      </>
    ),
  },
];

export function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  return (
    <nav className="tabbar" aria-label="Sections">
      {TABS.map((t) => {
        const on = t.id === active;
        return (
          <button
            key={t.id}
            className={on ? "tabbar__tab tabbar__tab--on" : "tabbar__tab"}
            aria-current={on ? "page" : undefined}
            onClick={() => onChange(t.id)}
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              {t.icon}
            </svg>
            <span>{t.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
