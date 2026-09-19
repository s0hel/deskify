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
    },
  });
}

export function useCancelBooking() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { bookingId: string; on: string; floorId: string }>({
    mutationFn: ({ bookingId }) => api<void>(`/bookings/${bookingId}`, { method: "DELETE" }),
    onSettled: (_d, _e, { on, floorId }) => {
      qc.invalidateQueries({ queryKey: keys.floorState(floorId, on) });
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
