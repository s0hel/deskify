import { describe, expect, it } from "vitest";

import { planUrl, siteSlug } from "./photos";

describe("siteSlug", () => {
  // The same cases as test_slugify_matches_the_clients_rule in
  // api/tests/test_floorplans.py. These two rules name the same files from
  // opposite ends -- the photo here, the plan SVG there -- so they are tested
  // against one list on purpose.
  it("matches the API's slugify", () => {
    expect(siteSlug("Tampa")).toBe("tampa");
    expect(siteSlug("Berlin Mitte")).toBe("berlin-mitte");
    expect(siteSlug("Singapore Raffles")).toBe("singapore-raffles");
    expect(siteSlug("  Spaced  Out  ")).toBe("spaced-out");
    expect(siteSlug("St. John's Wood")).toBe("st-john-s-wood");
  });
});

describe("planUrl", () => {
  it("resolves a key to the served path", () => {
    expect(planUrl("tampa-4f")).toBe("/plans/tampa-4f.svg");
  });

  it("is undefined for a floor nobody has drawn", () => {
    // FloorPlan takes planImageUrl as optional, so undefined -- not an empty
    // string -- is what makes it skip the <image> rather than request "".
    expect(planUrl(null)).toBeUndefined();
    expect(planUrl(undefined)).toBeUndefined();
    expect(planUrl("")).toBeUndefined();
  });
});
