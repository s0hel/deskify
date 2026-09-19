import { describe, expect, it } from "vitest";

import { EN, explain, plural } from "./messages";

describe("plural", () => {
  it("says person, not people, for one", () => {
    expect(plural(1, "person", "people")).toBe("1 person");
    expect(plural(2, "person", "people")).toBe("2 people");
  });

  it("defaults to adding an s", () => {
    expect(plural(1, "day")).toBe("1 day");
    expect(plural(3, "day")).toBe("3 days");
  });

  it("handles zero as plural, which is what English does", () => {
    expect(plural(0, "day")).toBe("0 days");
  });
});

describe("refusal messages", () => {
  const d = (code: string, params: Record<string, unknown>) => ({
    code,
    rule_key: "",
    scope: "",
    params,
  });

  it("never says '1 places'", () => {
    expect(explain(d("CAPACITY_EXCEEDED", { cap: 1 }))).toBe(
      "The office is full that day (1 place).",
    );
  });

  it("never says '1 days ahead'", () => {
    expect(explain(d("BOOKING_HORIZON_EXCEEDED", { limit_days: 1 }))).toBe(
      "You can book up to 1 day ahead.",
    );
  });

  it("never says '1 upcoming bookings'", () => {
    expect(explain(d("MAX_FUTURE_BOOKINGS", { limit: 1 }))).toBe(
      "You already have 1 upcoming booking.",
    );
  });

  it("falls back rather than showing a raw code to the user", () => {
    expect(explain(d("SOMETHING_NEW", {}))).toBe("That booking isn't allowed.");
  });

  it("has a message for every code the server can send", () => {
    // Mirrors app/errors.py and app/policy.py. If the server gains a denial
    // code, this list is where the client learns to say it.
    for (const code of [
      "RESOURCE_TAKEN",
      "CAPACITY_EXCEEDED",
      "SITE_CLOSED",
      "OUTSIDE_OPENING_HOURS",
      "RESOURCE_UNAVAILABLE",
      "ZONE_RESTRICTED",
      "DESK_ASSIGNED",
      "BOOKING_HORIZON_EXCEEDED",
      "MAX_FUTURE_BOOKINGS",
      "BOOKING_RELEASED",
    ]) {
      expect(EN[code], `no message for ${code}`).toBeTypeOf("function");
    }
  });
});
