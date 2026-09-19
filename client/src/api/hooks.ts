/**
 * Server state. TanStack Query throughout -- booking data IS server data, and
 * keeping a second copy of it creates two sources of truth about whether a
 * desk is free (TDD §10.1).
 *
 * Note the split between useFloor and useFloorState, which mirrors the API's
 * own split (TDD §5.2): the floor is heavy, stable and cacheable; the state is
 * small and volatile. The plan renders from cache while availability arrives
 * behind it.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "./client";

export interface Site {
  id: string;
  name: string;
  timezone: string;
  capacity_cap: number | null;
  check_in_enabled: boolean;
}

export interface DayAvailability {
  date: string;
  free: number;
  total: number;
  capacity_cap: number | null;
  my_booking_id: string | null;
  my_resource_name: string | null;
  declaration: string | null;
}

export interface FloorSummary {
  id: string;
  name: string;
  ordinal: number;
}

export interface ApiResource {
  id: string;
  kind: "desk" | "room";
  name: string;
  capacity: number;
  attributes: Record<string, unknown>;
  status: string;
  plan_x: number | null;
  plan_y: number | null;
}

export interface Floor {
  id: string;
  name: string;
  ordinal: number;
  plan_width: number | null;
  plan_height: number | null;
  resources: ApiResource[];
}

export type ResourceState = "free" | "booked" | "mine" | "unavailable" | "assigned";

export interface FloorState {
  date: string;
  states: Record<string, ResourceState>;
}

export interface Person {
  user_id: string;
  display_name: string;
  is_you: boolean;
  shared_teams: string[];
  resource_name: string | null;
  floor_name: string | null;
  declaration: string | null;
}

export interface WhosIn {
  date: string;
  in_office: Person[];
  away: Person[];
}

export interface ScheduleDay {
  date: string;
  kind: "office" | "remote" | "leave" | "none";
  resource_id: string | null;
  resource_name: string | null;
  floor_id: string | null;
  floor_name: string | null;
}

export interface PersonDetail {
  user_id: string;
  display_name: string;
  is_you: boolean;
  shared_teams: string[];
  in_office_days: number;
  horizon_days: number;
  schedule: ScheduleDay[];
}

export type Visibility = "everyone" | "team" | "nobody";

export interface Me {
  user_id: string;
  organization_id: string;
  email: string;
  display_name: string;
  locale: string;
  presence_visibility: Visibility;
  teams: string[];
}

export interface Booking {
  id: string;
  resource_id: string;
  user_id: string;
  local_date: string;
  status: string;
}

export const keys = {
  me: ["me"] as const,
  sites: ["sites"] as const,
  days: (siteId: string) => ["days", siteId] as const,
  people: (on: string) => ["people", on] as const,
  person: (id: string) => ["person", id] as const,
  floors: (siteId: string) => ["floors", siteId] as const,
  floor: (floorId: string) => ["floor", floorId] as const,
  floorState: (floorId: string, on: string) => ["floorState", floorId, on] as const,
};

export function useSites(enabled: boolean) {
  return useQuery({
    queryKey: keys.sites,
    queryFn: () => api<Site[]>("/sites"),
    enabled,
  });
}

/**
 * The week strip (FR-2.1). One request for seven days, rather than seven.
 *
 * It also feeds the refusal sheet's "nearest days with space", which is why it
 * lives here rather than being derived per screen.
 */
export function useDays(siteId: string | undefined) {
  return useQuery({
    queryKey: keys.days(siteId ?? ""),
    queryFn: () => api<DayAvailability[]>(`/sites/${siteId}/days?days=14`),
    enabled: Boolean(siteId),
    staleTime: 30 * 1000,
  });
}

export function useFloors(siteId: string | undefined) {
  return useQuery({
    queryKey: keys.floors(siteId ?? ""),
    queryFn: () => api<FloorSummary[]>(`/sites/${siteId}/floors`),
    enabled: Boolean(siteId),
  });
}

export function useFloor(floorId: string | undefined) {
  return useQuery({
    queryKey: keys.floor(floorId ?? ""),
    queryFn: () => api<Floor>(`/floors/${floorId}`),
    enabled: Boolean(floorId),
    // The plan and its desks change when an admin edits them, not minute to
    // minute. Availability is the volatile half, below.
    staleTime: 5 * 60 * 1000,
  });
}

export function useFloorState(floorId: string | undefined, on: string) {
  return useQuery({
    queryKey: keys.floorState(floorId ?? "", on),
    queryFn: () => api<FloorState>(`/floors/${floorId}/state?on=${on}`),
    enabled: Boolean(floorId),
    staleTime: 10 * 1000,
  });
}

export interface BookingVars {
  resourceId: string;
  on: string;
  slot?: "day" | "am" | "pm";
  floorId: string;
}

/**
 * Optimistic write with an honest rollback (FR-10.2).
 *
 * On rejection the UI does not merely revert -- it reverts and says why, using
 * the `code` from the problem+json body. "That desk was taken a moment ago" and
 * "Engineering can only book 14 days ahead" are different messages, and FR-6.9
 * exists so the user gets the right one.
 */
export function useCreateBooking() {
  const qc = useQueryClient();

  return useMutation<Booking, ApiError, BookingVars, { previous?: FloorState }>({
    mutationFn: ({ resourceId, on, slot = "day" }) =>
      api<Booking>("/bookings", {
        method: "POST",
        body: JSON.stringify({ resource_id: resourceId, on, slot }),
        // Generated when the USER ACTS, so a retry carries one key (TDD §11.3).
        idempotencyKey: crypto.randomUUID(),
      }),

    onMutate: async ({ resourceId, on, floorId }) => {
      const key = keys.floorState(floorId, on);
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<FloorState>(key);
      if (previous) {
        qc.setQueryData<FloorState>(key, {
          ...previous,
          states: { ...previous.states, [resourceId]: "mine" },
        });
      }
      return { previous };
    },

    onError: (_err, { on, floorId }, context) => {
      if (context?.previous) {
        qc.setQueryData(keys.floorState(floorId, on), context.previous);
      }
    },

    onSettled: (_data, _err, { on, floorId }) => {
      qc.invalidateQueries({ queryKey: keys.floorState(floorId, on) });
      qc.invalidateQueries({ queryKey: ["days"] });
      qc.invalidateQueries({ queryKey: ["bookings"] });
    },
  });
}

export function useCancelBooking() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { bookingId: string; on: string; floorId: string }>({
    mutationFn: ({ bookingId }) => api<void>(`/bookings/${bookingId}`, { method: "DELETE" }),
    onSettled: (_d, _e, { on, floorId }) => {
      qc.invalidateQueries({ queryKey: keys.floorState(floorId, on) });
      qc.invalidateQueries({ queryKey: ["days"] });
      qc.invalidateQueries({ queryKey: ["bookings"] });
    },
  });
}

export function useMyBookings(enabled: boolean) {
  return useQuery({
    queryKey: ["bookings"],
    queryFn: () => api<Booking[]>("/bookings"),
    enabled,
  });
}


/** FR-5.1 -- who is in on a day. Privacy filtering happens server-side. */
export function usePeople(on: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.people(on),
    queryFn: () => api<WhosIn>(`/people?on=${on}`),
    enabled: enabled && Boolean(on),
    staleTime: 30 * 1000,
  });
}

/** FR-5.2. A colleague who has hidden their days returns 404, and the UI says
 *  so plainly rather than pretending they do not exist. */
export function usePerson(userId: string | null) {
  return useQuery({
    queryKey: keys.person(userId ?? ""),
    queryFn: () => api<PersonDetail>(`/people/${userId}`),
    enabled: Boolean(userId),
  });
}

export function useMe(enabled: boolean) {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => api<Me>("/me"),
    enabled,
  });
}

/** FR-5.6. */
export function useSetVisibility() {
  const qc = useQueryClient();
  return useMutation<{ presence_visibility: Visibility }, ApiError, Visibility>({
    mutationFn: (presence_visibility) =>
      api("/me/privacy", {
        method: "PUT",
        body: JSON.stringify({ presence_visibility }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.me });
      // Your own change alters what everyone else sees, so drop those too.
      qc.invalidateQueries({ queryKey: ["people"] });
      qc.invalidateQueries({ queryKey: ["person"] });
    },
  });
}

/** FR-5.5 -- declare a day without booking, so the team view is complete. */
export function useSetDeclaration() {
  const qc = useQueryClient();
  return useMutation<unknown, ApiError, { on: string; kind: "office" | "remote" | "leave" | null }>(
    {
      mutationFn: ({ on, kind }) =>
        kind === null
          ? api(`/me/declarations/${on}`, { method: "DELETE" })
          : api(`/me/declarations/${on}`, {
              method: "PUT",
              body: JSON.stringify({ kind }),
            }),
      onSettled: () => {
        qc.invalidateQueries({ queryKey: ["days"] });
        qc.invalidateQueries({ queryKey: ["people"] });
      },
    },
  );
}
