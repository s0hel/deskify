import { useSetHomeSite, useSites, type Site } from "../api/hooks";
import { Sheet } from "../ui/Sheet";

/**
 * FR-1.9 -- pick the office you usually work from.
 *
 * Reached from two places, because there are two moments you want it: the
 * home screen, where you have just noticed it names the wrong city, and the
 * Me screen, where you go looking for settings. One component, so those two
 * routes cannot drift apart.
 *
 * The local time is shown against each office rather than the timezone name.
 * "America/New_York" is an identifier; "14:20 local" is the thing you
 * actually want to know before you book a desk there (FR-2.14).
 */

function localTime(timeZone: string, now = new Date()): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone,
      hour: "2-digit",
      minute: "2-digit",
    }).format(now);
  } catch {
    // An unknown zone must not take the whole sheet down with it.
    return timeZone;
  }
}

export function HomeSiteSheet({
  currentSiteId,
  onClose,
}: {
  currentSiteId: string | null;
  onClose: () => void;
}) {
  const sites = useSites(true);
  const setHomeSite = useSetHomeSite();
  const list: Site[] = [...(sites.data ?? [])].sort((a, b) => a.name.localeCompare(b.name));

  return (
    <Sheet open onClose={onClose} labelledBy="home-site-title">
      <h2 className="title" id="home-site-title">
        Your usual office
      </h2>
      <p className="meta" style={{ marginTop: 6 }}>
        The app opens here, and the days and desks you see are this
        office&apos;s. You can still book anywhere.
      </p>

      <div className="stack" style={{ marginTop: 14 }}>
        {sites.isLoading && <p className="meta">Loading offices…</p>}
        {!sites.isLoading && list.length === 0 && (
          <p className="meta">No offices are set up yet.</p>
        )}
        {list.map((site) => {
          const chosen = site.id === currentSiteId;
          return (
            <button
              key={site.id}
              className={chosen ? "choice choice--on" : "choice"}
              aria-pressed={chosen}
              disabled={setHomeSite.isPending}
              onClick={() => setHomeSite.mutate(site.id, { onSuccess: onClose })}
            >
              <span className="choice__label">{site.name}</span>
              <span className="choice__detail tabular">
                {localTime(site.timezone)} local
              </span>
              {chosen && (
                <span className="choice__tick" aria-hidden="true">
                  ✓
                </span>
              )}
            </button>
          );
        })}
      </div>

      {setHomeSite.isError && (
        <p className="meta" style={{ marginTop: 12, color: "var(--danger)" }}>
          That office could not be set. Try again.
        </p>
      )}
    </Sheet>
  );
}
