/**
 * What the console shows, and to whom. FR-1.8.
 *
 * The permission itself is server-side and tested there
 * (api/tests/test_admin.py walks the OpenAPI schema and asserts every admin
 * endpoint refuses an employee). What is being held HERE is the other half:
 * that a site admin is never shown a control that is going to refuse them.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { keys, type Me } from "../api/hooks";
import AdminConsole from "./AdminConsole";

const SITE = { id: "site-tampa", name: "Tampa", timezone: "America/New_York",
               capacity_cap: null, check_in_enabled: true };

function me(over: Partial<Me>): Me {
  return {
    user_id: "u1", organization_id: "o1", email: "priya@northwind.example",
    display_name: "Priya Raman", locale: "en", presence_visibility: "everyone",
    teams: ["Engineering"], home_site_id: SITE.id, home_site: SITE,
    is_admin: true, administered_site_ids: null,
    ...over,
  };
}

/** The console reads /me from the cache, so seeding it is enough -- no
 *  network, and the test states the grants it is exercising in one place. */
function mount(profile: Me) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  qc.setQueryData(keys.me, profile);
  return render(
    <QueryClientProvider client={qc}>
      <AdminConsole />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("the admin console", () => {
  it("gives an org admin every section", async () => {
    mount(me({ administered_site_ids: null }));
    await waitFor(() => screen.getByRole("navigation", { name: "Admin sections" }));

    const tabs = screen.getAllByRole("button", { pressed: false })
      .concat(screen.getAllByRole("button", { pressed: true }))
      .map((b) => b.textContent);
    expect(tabs).toEqual(expect.arrayContaining(["Offices", "Today", "People", "Activity"]));
  });

  it("does not offer a site admin the sections that would refuse them", async () => {
    // People and Activity are org-wide. Rendering the tab and letting the
    // API answer 403 would mean the only way to find out is to press it.
    mount(me({ administered_site_ids: ["site-tampa"] }));
    await waitFor(() => screen.getByRole("navigation", { name: "Admin sections" }));

    expect(screen.queryByRole("button", { name: "People" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Activity" })).toBeNull();
    expect(screen.getByRole("button", { name: "Offices" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Today" })).toBeTruthy();
  });

  it("names the scope it is operating at, because the two consoles differ", async () => {
    mount(me({ administered_site_ids: ["site-tampa"] }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Your office"),
    );
  });

  it("says organization when the grant is org-wide", async () => {
    mount(me({ administered_site_ids: null }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
        "Your organization",
      ),
    );
  });

  it("offers a way out only when there is somewhere to go back to", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(keys.me, me({}));
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <AdminConsole />
      </QueryClientProvider>,
    );
    await waitFor(() => screen.getByRole("navigation", { name: "Admin sections" }));
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();

    const onClose = vi.fn();
    rerender(
      <QueryClientProvider client={qc}>
        <AdminConsole onClose={onClose} />
      </QueryClientProvider>,
    );
    screen.getByRole("button", { name: "Done" }).click();
    expect(onClose).toHaveBeenCalled();
  });
});
