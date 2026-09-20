import { firstName } from "../ui/bits";
import { officePhoto } from "./photos";

/**
 * The first thing anyone sees: which office, who they are, what day it is.
 *
 * The office is named because the app is not single-site -- everything below
 * this card (availability, the plan, the week strip) is scoped to one
 * building, and a screen that does not say which one is quietly lying when
 * you are on a trip. It is a button rather than a heading for the same
 * reason: the place you notice you are looking at the wrong office is the
 * place to change it (FR-1.9).
 *
 * An office with a photograph gets its photograph. One without gets the drawn
 * illustration below -- inline SVG in the token palette, so it themes with
 * everything else and costs no request, with lit windows derived from the
 * site id so two offices look different and one office always looks the same.
 *
 * The fallback is not a placeholder for a missing asset; it is what most
 * tenants will actually see. Photographing every office is a thing a customer
 * does eventually, if at all, and the screen has to be finished before they
 * do.
 */

const WINDOW_COLS = 6;
const WINDOW_ROWS = 5;

/**
 * Which windows have the lights on. Deterministic in the site id: a hash, not
 * a random, because a building that reshuffles itself on every render reads as
 * a bug even when nobody can say why.
 */
export function litWindows(siteId: string, count: number): boolean[] {
  let h = 2166136261;
  for (let i = 0; i < siteId.length; i++) {
    h ^= siteId.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Array.from({ length: count }, (_, i) => {
    h ^= h << 13;
    h ^= h >>> 17;
    h ^= h << 5;
    // Roughly half lit. All-dark reads as closed, all-lit as a render bug.
    return ((h >>> 0) % 10 + i) % 3 !== 0;
  });
}

function OfficeBuilding({ siteId }: { siteId: string }) {
  const lit = litWindows(siteId, WINDOW_COLS * WINDOW_ROWS);

  return (
    <svg
      className="hero__art"
      viewBox="0 0 320 140"
      preserveAspectRatio="xMidYMax slice"
      aria-hidden="true"
    >
      {/* Sky, then the two blocks behind, then ours in front. Depth comes from
          three flat tones rather than a gradient, which survives dark mode. */}
      <rect className="hero__sky" x="0" y="0" width="320" height="140" />
      <circle className="hero__sun" cx="262" cy="34" r="16" />

      <rect className="hero__far" x="14" y="52" width="58" height="88" rx="4" />
      <rect className="hero__far" x="240" y="66" width="66" height="74" rx="4" />
      <rect className="hero__mid" x="62" y="38" width="44" height="102" rx="4" />
      <rect className="hero__mid" x="214" y="48" width="38" height="92" rx="4" />

      {/* The building the greeting is about. */}
      <rect className="hero__near" x="104" y="26" width="112" height="114" rx="6" />
      <rect className="hero__near" x="126" y="14" width="68" height="16" rx="5" />

      {Array.from({ length: WINDOW_ROWS }, (_, row) =>
        Array.from({ length: WINDOW_COLS }, (_, col) => (
          <rect
            key={`${row}-${col}`}
            className={lit[row * WINDOW_COLS + col] ? "hero__win hero__win--lit" : "hero__win"}
            x={114 + col * 16}
            y={38 + row * 17}
            width="10"
            height="11"
            rx="1.5"
          />
        )),
      )}

      {/* A door, so the grid of windows reads at a building's scale rather
          than as a barcode. There is no ground line: the card's own bottom
          edge is the pavement, and a bar drawn across it only cut the door
          in half. */}
      <rect className="hero__door" x="150" y="120" width="20" height="20" rx="2" />
    </svg>
  );
}

export function WelcomeHero({
  siteId,
  siteName,
  name,
  todayLabel,
  chosen,
  onChangeSite,
}: {
  siteId: string;
  siteName: string;
  name: string;
  todayLabel: string;
  /** False while the office is the API's fallback rather than their choice. */
  chosen: boolean;
  onChangeSite: () => void;
}) {
  const photo = officePhoto(siteName);

  return (
    <section className="hero">
      {photo ? (
        <img
          className="hero__art hero__art--photo"
          src={photo}
          alt=""
          /* Decorative: the office is named in the heading right below it,
             so a description here would only repeat it to a screen reader. */
          aria-hidden="true"
        />
      ) : (
        <OfficeBuilding siteId={siteId} />
      )}
      <div className="hero__body">
        <h2 className="display hero__greeting">
          Welcome to {siteName}, {firstName(name)}
        </h2>
        <p className="meta hero__date">Today is {todayLabel}</p>
        <button className="hero__switch" onClick={onChangeSite}>
          {chosen ? "Change your office" : "Is this your usual office?"}
        </button>
      </div>
    </section>
  );
}
