import { describe, expect, it } from "vitest";

import { initials } from "./bits";

describe("initials", () => {
  it("takes first and last for a full name", () => {
    expect(initials("Priya Raman")).toBe("PR");
    expect(initials("Marcus Hale")).toBe("MH");
  });

  it("uses first and LAST, not first and second", () => {
    expect(initials("Ana Maria Torres")).toBe("AT");
  });

  it("gives a single-word name two letters, not one", () => {
    // A one-character avatar reads as an icon rather than a person.
    expect(initials("Priya")).toBe("PR");
  });

  it("survives stray whitespace", () => {
    expect(initials("  Priya   Raman  ")).toBe("PR");
  });

  it("does not crash on an empty name", () => {
    expect(initials("")).toBe("?");
    expect(initials("   ")).toBe("?");
  });
});
