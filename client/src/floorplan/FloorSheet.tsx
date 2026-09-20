import type { FloorSummary } from "../api/hooks";
import { Sheet } from "../ui/Sheet";

/**
 * Which floor am I looking at, and which one has room?
 *
 * The second question is why this shows free counts rather than a list of
 * names: nobody opens a floor picker to admire the naming scheme. "3F · 12
 * free" is the whole reason to switch, and a floor with nothing left says so
 * before you go and look.
 *
 * Ordered by the API, lowest floor first, so the list reads like a building
 * rather than like a database.
 */
export function FloorSheet({
  floors,
  currentId,
  dayLabel,
  onPick,
  onClose,
}: {
  floors: FloorSummary[];
  currentId: string | undefined;
  dayLabel: string;
  onPick: (floorId: string) => void;
  onClose: () => void;
}) {
  return (
    <Sheet open onClose={onClose} labelledBy="floor-title">
      <h2 className="title" id="floor-title">
        Choose a floor
      </h2>
      <p className="meta" style={{ marginTop: 6 }}>
        Free desks shown for {dayLabel}.
      </p>

      <div className="stack" style={{ marginTop: 14 }}>
        {floors.map((floor) => {
          const chosen = floor.id === currentId;
          const full = floor.free === 0;
          return (
            <button
              key={floor.id}
              className={chosen ? "choice choice--on" : "choice"}
              aria-pressed={chosen}
              onClick={() => {
                onPick(floor.id);
                onClose();
              }}
            >
              <span className="choice__label tabular">{floor.name}</span>
              <span className="choice__detail">
                {full ? (
                  "No desks left"
                ) : (
                  <>
                    <span className="count-free tabular">{floor.free} free</span> of{" "}
                    <span className="tabular">{floor.total}</span>
                  </>
                )}
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
    </Sheet>
  );
}
