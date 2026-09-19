/**
 * Denial codes become human sentences HERE, on the client, from code + params
 * (FR-6.9 + FR-10.4). The server's English string is a fallback we do not show.
 *
 * Four launch languages means these live in the i18n catalogues; this module is
 * the shape, with `en` inline.
 */

import type { Denial } from "./client";

type Formatter = (p: Record<string, any>) => string;

/**
 * "1 person", not "1 people".
 *
 * Small, but these strings are the product's voice at the exact moment it is
 * telling someone no, and a grammar slip there reads as carelessness.
 */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${Math.abs(n) === 1 ? one : many}`;
}

export const EN: Record<string, Formatter> = {
  RESOURCE_TAKEN: () => "Someone booked that desk a moment ago.",
  CAPACITY_EXCEEDED: (p) => `The office is full that day (${plural(p.cap, "place")}).`,
  SITE_CLOSED: (p) => `The office is closed that day: ${p.reason}.`,
  OUTSIDE_OPENING_HOURS: (p) => `That site is open ${p.opens}–${p.closes}.`,
  RESOURCE_UNAVAILABLE: () => "That desk is out of service.",
  ZONE_RESTRICTED: () => "That area is reserved for another team.",
  DESK_ASSIGNED: () => "That desk belongs to someone else.",
  BOOKING_HORIZON_EXCEEDED: (p) => `You can book up to ${plural(p.limit_days, "day")} ahead.`,
  MAX_FUTURE_BOOKINGS: (p) =>
    `You already have ${plural(p.limit, "upcoming booking")}.`,
  BOOKING_RELEASED: () => "That booking was released because it wasn't checked into.",
};

export function explain(denial: Denial, catalogue = EN): string {
  const fmt = catalogue[denial.code];
  return fmt ? fmt(denial.params) : "That booking isn't allowed.";
}
