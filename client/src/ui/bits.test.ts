import { describe, expect, it } from "vitest";

import { firstName, initials } from "./bits";

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

describe("firstName", () => {
  it("greets someone by the name they go by", () => {
    expect(firstName("Priya Raman")).toBe("Priya");
    expect(firstName("Ana Maria Torres")).toBe("Ana");
  });

  it("uses the whole thing when there is only one word", () => {
    expect(firstName("Priya")).toBe("Priya");
  });

  it("survives stray whitespace", () => {
    expect(firstName("  Priya   Raman  ")).toBe("Priya");
  });

  it("returns empty rather than undefined for an empty name", () => {
    // "Welcome to Tampa, undefined" is the failure this guards against.
    expect(firstName("")).toBe("");
    expect(firstName("   ")).toBe("");
  });
});
