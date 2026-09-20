import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WelcomeHero, litWindows } from "./WelcomeHero";

const props = {
  siteId: "11111111-2222-3333-4444-555555555555",
  siteName: "Tampa",
  name: "Priya Raman",
  todayLabel: "Saturday, 20 September",
  chosen: true,
  onChangeSite: () => {},
};

describe("the welcome hero", () => {
  it("names the office and the person, not the account", () => {
    render(<WelcomeHero {...props} />);
    expect(screen.getByRole("heading").textContent).toBe("Welcome to Tampa, Priya");
  });

  it("says what day it is", () => {
    render(<WelcomeHero {...props} />);
    expect(screen.getByText("Today is Saturday, 20 September")).toBeTruthy();
  });

  it("offers a way to change the office right where you notice it is wrong", async () => {
    const onChangeSite = vi.fn();
    render(<WelcomeHero {...props} onChangeSite={onChangeSite} />);
    screen.getByRole("button", { name: "Change your office" }).click();
    expect(onChangeSite).toHaveBeenCalled();
  });

  it("asks, rather than states, when the office is only a fallback", () => {
    // home_site_id is null: the API guessed, so the hero must not imply the
    // user chose Tampa.
    render(<WelcomeHero {...props} chosen={false} />);
    expect(screen.getByRole("button", { name: "Is this your usual office?" })).toBeTruthy();
  });
});

describe("lit windows", () => {
  it("is stable for a site, so the building does not flicker on re-render", () => {
    expect(litWindows("site-a", 30)).toEqual(litWindows("site-a", 30));
  });

  it("differs between sites, so two offices do not look identical", () => {
    expect(litWindows("site-a", 30)).not.toEqual(litWindows("site-b", 30));
  });

  it("is never all on or all off -- both read as a bug rather than a building", () => {
    for (const id of ["site-a", "site-b", "site-c", "", "0"]) {
      const lit = litWindows(id, 30);
      expect(lit.some(Boolean)).toBe(true);
      expect(lit.some((v) => !v)).toBe(true);
    }
  });
});
