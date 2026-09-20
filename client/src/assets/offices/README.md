# Office photographs

One image per site, named after the site's slug: `Berlin Mitte` becomes
`berlin-mitte.jpg`. `siteSlug` in `../../booking/photos.ts` is the rule, and
`slugify` in `api/app/floorplans.py` is the same rule on the other side.

They are picked up by a glob, not by named imports, so **a missing photo is
not a build error** — the welcome hero falls back to its drawn illustration.
Adding an office means dropping a file in here and nothing else.

**These are committed**, because Vercel builds from git: a photo that is not
in the repository does not exist on the deployed site.

The ones here are **iStock comps — watermarked, unlicensed previews**, kept
deliberately so the deployed demo shows real buildings. The watermark sits
across the middle of the hero, which is the first thing anyone sees. Replace
them with licensed files under the same names before this is shown to anyone
outside the team; nothing in the code has to change.

Files sitting in `../` rather than here are ignored by the glob and by git —
that is the staging area for photos not yet assigned to an office.

Roughly 3:2, 1024px wide is plenty — the hero renders it about 340×132 CSS
pixels and crops to the centre.
