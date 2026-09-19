/**
 * Day handling on the client.
 *
 * The rule from TDD §3.4 applies here too: a day belongs to the SITE, not the
 * device. The client derives dates in the site's timezone and sends bare
 * YYYY-MM-DD strings, so someone in London booking a Berlin desk never shifts a
 * day by accident.
 */

export function siteToday(timeZone: string, now = new Date()): string {
  // en-CA formats as YYYY-MM-DD, which is what the API expects.
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(now);
}

export function addDays(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

export function nextDays(timeZone: string, count: number, now = new Date()): string[] {
  const start = siteToday(timeZone, now);
  return Array.from({ length: count }, (_, i) => addDays(start, i));
}

export function weekdayLabel(isoDate: string, locale = "en-GB"): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  // Render from a fixed UTC instant so the label cannot drift by a day.
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}
