import { describe, expect, it } from "vitest";

import { isoWeekday, weekStart } from "./dates";

describe("weekStart", () => {
  it("snaps a mid-week day back to its Monday", () => {
    // 2026-09-23 is a Wednesday.
    expect(weekStart("2026-09-23")).toBe("2026-09-21");
  });

  it("leaves a Monday alone", () => {
    expect(weekStart("2026-09-21")).toBe("2026-09-21");
  });

  it("treats Sunday as the END of its week, not the start", () => {
    // The classic off-by-one: JS getUTCDay puts Sunday at 0.
    expect(weekStart("2026-09-20")).toBe("2026-09-14");
  });

  it("crosses a month boundary", () => {
    // 2026-10-01 is a Thursday.
    expect(weekStart("2026-10-01")).toBe("2026-09-28");
  });

  it("crosses a year boundary", () => {
    // 2027-01-01 is a Friday.
    expect(weekStart("2027-01-01")).toBe("2026-12-28");
  });
});

describe("isoWeekday", () => {
  it("numbers Monday as 1 and Sunday as 7", () => {
    expect(isoWeekday("2026-09-21")).toBe(1);
    expect(isoWeekday("2026-09-22")).toBe(2);
    expect(isoWeekday("2026-09-27")).toBe(7);
  });

  it("matches what the API sends for anchor days", () => {
    // Engineering anchors on [2, 4] -- Tuesday and Thursday.
    const week = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"];
    expect(week.map(isoWeekday).filter((d) => [2, 4].includes(d))).toEqual([2, 4]);
  });
});
