/**
 * The admin console's server state. FR-8.x.
 *
 * Kept out of api/hooks.ts on purpose: this module is only imported from
 * `src/admin/`, which is behind a lazy boundary (TDD §10.1), so none of it
 * reaches the employee bundle. Putting one admin hook into hooks.ts would
 * pull the whole file across that boundary.
 *
 * Every mutation here invalidates broadly rather than patching the cache.
 * A console edit is rare and consequential -- a refetch costs one request and
 * cannot show a stale desk count, which is the failure an admin screen must
 * not have.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "./client";
import type { Site } from "./hooks";

export interface AdminSite extends Site {
  opening_hours: { open?: string; close?: string };
  geofence_lat: number | null;
  geofence_lng: number | null;
  geofence_radius_m: number;
}

export interface AdminFloor {
  id: string;
  site_id: string;
  name: string;
  ordinal: number;
  plan_asset_key: string | null;
  plan_width: number | null;
  plan_height: number | null;
  /** Zero means an unfinished import, and the screen says so. */
  desk_count: number;
}

export interface AdminZone {
  id: string;
  floor_id: string;
  name: string;
  polygon: unknown[];
  restricted_to_group_id: string | null;
  resource_count: number;
}

export type RoleName = "team_lead" | "site_admin" | "org_admin";

export interface RoleGrant {
  role: RoleName;
  scope_type: "org" | "site" | "group";
  scope_id: string | null;
  scope_name: string | null;
}

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  status: "active" | "deactivated";
  home_site_id: string | null;
  presence_visibility: string;
  teams: string[];
  roles: RoleGrant[];
  /**
   * A COUNT, never the bookings themselves. The directory lists everyone
   * regardless of presence privacy -- an employer knows who works there --
   * but it must not become a way around FR-5.6, so it never says which desk
   * on which day.
   */
  future_bookings: number;
}

export interface AdminGroup {
  id: string;
  name: string;
  kind: string;
  anchor_days: number[];
  member_count: number;
}

export interface AdminBooking {
  id: string;
  user_id: string;
  user_name: string;
  resource_id: string;
  resource_name: string;
  site_id: string;
  local_date: string;
  status: string;
  booked_by: string | null;
}

export interface AuditEntry {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown>;
  at: string;
}

export const adminKeys = {
  floors: ["admin", "floors"] as const,
  zones: ["admin", "zones"] as const,
  users: (q: string) => ["admin", "users", q] as const,
  groups: ["admin", "groups"] as const,
  bookings: (on: string, siteId: string) => ["admin", "bookings", on, siteId] as const,
  audit: ["admin", "audit"] as const,
};

/** Everything an edit could plausibly have changed, including the employee
 *  app's own caches -- an admin renaming a floor is looking at the same data
 *  the Spaces tab is showing. */
function invalidateEverything(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["admin"] });
  qc.invalidateQueries({ queryKey: ["sites"] });
  qc.invalidateQueries({ queryKey: ["floors"] });
  qc.invalidateQueries({ queryKey: ["floor"] });
  qc.invalidateQueries({ queryKey: ["floorState"] });
  qc.invalidateQueries({ queryKey: ["days"] });
  qc.invalidateQueries({ queryKey: ["me"] });
}

function useAdminMutation<TResult, TVars>(fn: (vars: TVars) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation<TResult, ApiError, TVars>({
    mutationFn: fn,
    onSuccess: () => invalidateEverything(qc),
  });
}

export function useAdminFloors() {
  return useQuery({ queryKey: adminKeys.floors, queryFn: () => api<AdminFloor[]>("/admin/floors") });
}

export function useAdminZones() {
  return useQuery({ queryKey: adminKeys.zones, queryFn: () => api<AdminZone[]>("/admin/zones") });
}

export function useAdminUsers(q: string, enabled: boolean) {
  return useQuery({
    queryKey: adminKeys.users(q),
    queryFn: () => api<AdminUser[]>(`/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`),
    enabled,
  });
}

export function useAdminGroups(enabled: boolean) {
  return useQuery({
    queryKey: adminKeys.groups,
    queryFn: () => api<AdminGroup[]>("/admin/groups"),
    enabled,
  });
}

export function useAdminBookings(on: string, siteId: string, enabled: boolean) {
  return useQuery({
    queryKey: adminKeys.bookings(on, siteId),
    queryFn: () =>
      api<AdminBooking[]>(`/admin/bookings?on=${on}${siteId ? `&site_id=${siteId}` : ""}`),
    enabled,
  });
}

export function useAudit(enabled: boolean) {
  return useQuery({
    queryKey: adminKeys.audit,
    queryFn: () => api<AuditEntry[]>("/audit?limit=100"),
    enabled,
  });
}

export function useUpdateSite() {
  return useAdminMutation<AdminSite, { siteId: string; patch: Partial<AdminSite> }>(
    ({ siteId, patch }) =>
      api(`/sites/${siteId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  );
}

export function useCreateSite() {
  return useAdminMutation<AdminSite, Record<string, unknown>>((body) =>
    api("/sites", { method: "POST", body: JSON.stringify(body) }),
  );
}

export function useCreateFloor() {
  return useAdminMutation<AdminFloor, Record<string, unknown>>((body) =>
    api("/floors", { method: "POST", body: JSON.stringify(body) }),
  );
}

export function useUpdateFloor() {
  return useAdminMutation<AdminFloor, { floorId: string; patch: Record<string, unknown> }>(
    ({ floorId, patch }) =>
      api(`/floors/${floorId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  );
}

export function useCreateZone() {
  return useAdminMutation<AdminZone, Record<string, unknown>>((body) =>
    api("/zones", { method: "POST", body: JSON.stringify(body) }),
  );
}

export function useUpdateZone() {
  return useAdminMutation<AdminZone, { zoneId: string; patch: Record<string, unknown> }>(
    ({ zoneId, patch }) =>
      api(`/zones/${zoneId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  );
}

export function useDeleteZone() {
  return useAdminMutation<void, string>((zoneId) =>
    api(`/zones/${zoneId}`, { method: "DELETE" }),
  );
}

export function useCreateUser() {
  return useAdminMutation<AdminUser, Record<string, unknown>>((body) =>
    api("/admin/users", { method: "POST", body: JSON.stringify(body) }),
  );
}

export function useSetUserRoles() {
  return useAdminMutation<
    AdminUser,
    { userId: string; roles: { role: RoleName; scope_id?: string | null }[] }
  >(({ userId, roles }) =>
    api(`/admin/users/${userId}/roles`, { method: "PUT", body: JSON.stringify({ roles }) }),
  );
}

export function useDeactivateUser() {
  return useAdminMutation<{ user: AdminUser; released: number }, string>((userId) =>
    api(`/admin/users/${userId}/deactivate`, { method: "POST" }),
  );
}

export function useReactivateUser() {
  return useAdminMutation<AdminUser, string>((userId) =>
    api(`/admin/users/${userId}/reactivate`, { method: "POST" }),
  );
}

export function useUpdateGroup() {
  return useAdminMutation<AdminGroup, { groupId: string; patch: Record<string, unknown> }>(
    ({ groupId, patch }) =>
      api(`/admin/groups/${groupId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  );
}

export function useTakeOutOfService() {
  return useAdminMutation<
    { resource: Record<string, unknown>; released: number },
    { resourceId: string; reason: string; releaseBookings: boolean }
  >(({ resourceId, reason, releaseBookings }) =>
    api(`/resources/${resourceId}/out-of-service`, {
      method: "POST",
      body: JSON.stringify({ reason, release_bookings: releaseBookings }),
    }),
  );
}

export function useReturnToService() {
  return useAdminMutation<{ resource: Record<string, unknown>; released: number }, string>(
    (resourceId) => api(`/resources/${resourceId}/out-of-service`, { method: "DELETE" }),
  );
}
