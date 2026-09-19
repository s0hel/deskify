/**
 * A bottom sheet.
 *
 * This is the app's one modal surface: desk detail, refusals, confirmations.
 * The reference design uses it instead of alerts everywhere, and the reason is
 * that an alert can only say no, whereas a sheet has room to offer a way
 * forward (see RefusalSheet).
 */

import { useEffect, useRef, type ReactNode } from "react";

export function Sheet({
  open,
  onClose,
  labelledBy,
  children,
}: {
  open: boolean;
  onClose: () => void;
  labelledBy: string;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);

    // Move focus into the sheet so a screen reader lands on the thing that
    // just appeared rather than staying behind it.
    const first = panel.current?.querySelector<HTMLElement>(
      "button, [href], input, [tabindex]:not([tabindex='-1'])",
    );
    first?.focus();

    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <button className="scrim" aria-label="Close" onClick={onClose} />
      <div
        ref={panel}
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
      >
        <div className="sheet__grab" />
        {children}
      </div>
    </>
  );
}
