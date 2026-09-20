# Office photographs

One image per site, named after the site's slug: `Berlin Mitte` becomes
`berlin-mitte.jpg`. `siteSlug` in `../../booking/photos.ts` is the rule, and
`slugify` in `api/app/floorplans.py` is the same rule on the other side.

They are picked up by a glob, not by named imports, so **a missing photo is
not a build error** — the welcome hero falls back to its drawn illustration.
Adding an office means dropping a file in here and nothing else.

`*.jpg` in this directory is **gitignored**, deliberately. The images this was
built against are iStock comps: watermarked, unlicensed previews. Committing
those would put someone else's marked-up property in the repository and ship a
watermark across the middle of the first screen anyone sees. Drop licensed
files in with these names and they appear; the repository stays clean either
way.

Files sitting in `../` rather than here are ignored by the glob — that is the
staging area for photos not yet assigned to an office. They are gitignored too,
so trying one out cannot commit it by accident.

Roughly 3:2, 1024px wide is plenty — the hero renders it about 340×132 CSS
pixels and crops to the centre.
