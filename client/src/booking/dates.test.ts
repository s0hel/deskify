import { describe, expect, it } from "vitest";

import { addDays, nextDays, siteToday, weekdayLabel } from "./dates";

describe("site-local dates", () => {
  it("uses the site's timezone, not the device's", () => {
    // 22:30 UTC is already the next day in Berlin, and still the same day in LA.
    const instant = new Date("2026-10-01T22:30:00Z");
    expect(siteToday("Europe/Berlin", instant)).toBe("2026-10-02");
    expect(siteToday("America/Los_Angeles", instant)).toBe("2026-10-01");
  });

  it("gives two sites two different todays for one instant", () => {
    const instant = new Date("2026-10-02T03:00:00Z");
    expect(siteToday("Europe/Berlin", instant)).not.toBe(
      siteToday("America/Los_Angeles", instant),
    );
  });

  it("crosses a month boundary", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
  });

  it("crosses a year boundary", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });

  it("survives a DST transition without losing or repeating a day", () => {
    // Europe/Berlin leaves DST on 25 Oct 2026.
    const week = nextDays("Europe/Berlin", 5, new Date("2026-10-23T09:00:00Z"));
    expect(week).toEqual([
      "2026-10-23",
      "2026-10-24",
      "2026-10-25",
      "2026-10-26",
      "2026-10-27",
    ]);
    expect(new Set(week).size).toBe(week.length);
  });

  it("labels a date without drifting by a day", () => {
    // 1 Nov 2026 is a Sunday. A naive local-time Date would shift this west of UTC.
    expect(weekdayLabel("2026-11-01")).toMatch(/Sun/);
  });

  it("returns the requested number of consecutive days", () => {
    const days = nextDays("Europe/Berlin", 7, new Date("2026-10-01T09:00:00Z"));
    expect(days).toHaveLength(7);
    expect(days[0]).toBe("2026-10-01");
    expect(days[6]).toBe("2026-10-07");
  });
});
