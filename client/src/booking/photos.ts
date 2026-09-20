/**
 * A photograph of each office, when there is one.
 *
 * Resolved with a glob rather than named imports, because the set of offices
 * is data and the set of photos is whatever someone has dropped in. A named
 * import of a file that is not there fails the BUILD -- so a tenant that adds
 * a seventh office, or a checkout with no photos in it at all, would stop
 * compiling. This way a missing photo is a fallback, which is what it is.
 *
 * Filenames are the site's slug: `Berlin Mitte` -> `berlin-mitte.jpg`. The
 * same rule lives in `slugify` in api/app/floorplans.py, which names the plan
 * SVGs; `siteSlug` below is the client half and is tested against the same
 * cases.
 */

const PHOTOS = import.meta.glob<string>("../assets/offices/*.jpg", {
  eager: true,
  query: "?url",
  import: "default",
});

/** `Berlin Mitte` -> `berlin-mitte`. Must agree with api/app/floorplans.py. */
export function siteSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function officePhoto(siteName: string): string | null {
  const slug = siteSlug(siteName);
  for (const [path, url] of Object.entries(PHOTOS)) {
    if (path.endsWith(`/${slug}.jpg`)) return url;
  }
  return null;
}

/** The drawing behind the desks. Served from client/public/plans. */
export function planUrl(key: string | null | undefined): string | undefined {
  return key ? `/plans/${key}.svg` : undefined;
}
