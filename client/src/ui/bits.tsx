/** Small shared pieces, so the token vocabulary stays in one place. */

/**
 * Two letters, always. A single-word name falls back to its first two letters,
 * because a one-character avatar reads as an icon rather than a person.
 */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

export function Chevron() {
  return (
    <svg className="chevron" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * What to call someone in a greeting.
 *
 * "Welcome to Tampa, Priya Raman" reads like a boarding announcement, so the
 * hero uses the first word only -- and falls back to the whole string rather
 * than to nothing when there is no space in it.
 */
export function firstName(name: string): string {
  const [first] = name.trim().split(/\s+/).filter(Boolean);
  return first ?? "";
}
