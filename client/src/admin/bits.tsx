/**
 * Shared pieces of the console. Small, and deliberately not in src/ui:
 * everything here is behind the lazy admin boundary (TDD §10.1), and an
 * import from src/ui/ in the other direction would drag it into the employee
 * bundle.
 */

import { useState, type ReactNode } from "react";

import { ApiError } from "../api/client";

/**
 * What went wrong, in the server's own words.
 *
 * The admin API's refusals carry the part that matters -- how many bookings,
 * which site, what to do instead -- and `detail` is the only place it exists.
 * A generic "something went wrong" here would throw away the answer to the
 * question the admin is about to ask.
 */
export function Problem({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    error instanceof ApiError
      ? (error.detail ??
        (error.status === 403
          ? "You do not have permission to do that."
          : "That change was refused."))
      : "Could not reach the API.";
  return (
    <p className="admin-problem" role="alert">
      {message}
    </p>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="admin-field">
      <span className="admin-field__label">{label}</span>
      {children}
      {hint && <span className="admin-field__hint">{hint}</span>}
    </label>
  );
}

/**
 * A destructive action, behind one confirmation that says what will happen.
 *
 * Deliberately not a `window.confirm`: the consequence is the point, and
 * "Deactivate Ren Takahashi? This releases 3 upcoming desks." is a different
 * decision from "Are you sure?".
 */
export function Confirm({
  label,
  consequence,
  busy,
  onConfirm,
}: {
  label: string;
  consequence: string;
  busy?: boolean;
  onConfirm: () => void;
}) {
  const [armed, setArmed] = useState(false);

  if (!armed) {
    return (
      <button className="btn btn--quiet btn--danger-text" onClick={() => setArmed(true)}>
        {label}
      </button>
    );
  }
  return (
    <div className="admin-confirm">
      <p className="meta">{consequence}</p>
      <div className="admin-confirm__row">
        <button className="btn btn--danger" disabled={busy} onClick={onConfirm}>
          {busy ? "Working…" : label}
        </button>
        <button className="btn btn--quiet" disabled={busy} onClick={() => setArmed(false)}>
          Keep it
        </button>
      </div>
    </div>
  );
}

/** A screenful of nothing, saying which nothing it is. */
export function Empty({ children }: { children: ReactNode }) {
  return <p className="admin-empty">{children}</p>;
}

export function Tag({ tone, children }: { tone?: "warn" | "quiet"; children: ReactNode }) {
  return <span className={tone ? `admin-tag admin-tag--${tone}` : "admin-tag"}>{children}</span>;
}
