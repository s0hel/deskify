import { initials } from "../ui/bits";

/**
 * A stable colour per person, derived from their id.
 *
 * Deliberately not random and not tied to team: someone's avatar should look
 * the same everywhere in the app, and change only when they do.
 */
const PALETTE = [
  "var(--state-free)",
  "var(--state-person)",
  "var(--clay)",
  "var(--state-zone)",
  "#5b6cc4",
  "#8a6d3b",
];

function hue(id: string): string {
  let sum = 0;
  for (let i = 0; i < id.length; i++) sum = (sum + id.charCodeAt(i)) % 997;
  return PALETTE[sum % PALETTE.length];
}

export function Avatar({
  id,
  name,
  you = false,
  size = 40,
}: {
  id: string;
  name: string;
  you?: boolean;
  size?: number;
}) {
  return (
    <span
      className="avatar"
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        background: you ? "var(--accent)" : hue(id),
        fontSize: size < 36 ? 12 : 14,
      }}
    >
      {initials(name)}
    </span>
  );
}
