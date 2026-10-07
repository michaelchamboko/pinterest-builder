---
title: "Pinterest Pilot Implementation and Live Test"
tags: [pinterest, pilot, automation]
status: active
created: 2026-09-17
---

## Implemented

Local resumable batches, exact approved-URL parsing, source and link checks, ImageKit upload receipts and reconciliation, original-byte media verification, locked UTF-8 CSV export, UTC scheduling, and duplicate-publication guard.

43 tests pass with bundled Python. Independent review found no remaining actionable issues after atomic receipt publication and original-delivery fixes.

ImageKit and Short.io keys are stored locally, never in this log. Both authenticated. Short.io pilot link: https://vettedsaasblueprint.s.gy/75CBlK ; verified exact first redirect to approved https://try.elevenlabs.io/izj2b165mcsj .

## Pilot assets

All ten 1024x1536 images generated with built-in image generation and visually reviewed. Five guides and five promotions, each with affiliate disclosure. Files, prompts, source checks and metadata live under `batches/elevenlabs-pilot/`.

ImageKit folder: `/pinterest/elevenlabs-pilot/elevenlabs-5bd5f93cf3f0/`. Default CDN optimization changed bytes; documented `tr:orig-true` delivery passes exact verification. No account setting changed.

Seven uploads completed before a network timeout at image eight. Resume checks remote paths first and never overwrites existing files. Final upload/import result will be appended below.

### Final result

All ten ImageKit assets uploaded and public original-file URLs verified against local bytes. Network retries resumed without duplicating completed work. CSV `batches/elevenlabs-pilot/pinterest-elevenlabs-pilot-v001.csv` exported at 2026-09-17 17:01:14 UTC, ten rows. First date blank; remaining rows 17:31:14 through 21:31:14 UTC, every thirty minutes. Exact eight sample columns preserved.

Pinterest browser file chooser failed three times (role click, actual input click, accessibility click), before any file selection or transmission. No CSV submitted and no Pinterest Pins created by this test. Stop browser retries; user can manually select the validated CSV at https://za.pinterest.com/settings/bulk-create-pins/ . Refresh export timestamps if delayed. Browser tab preserved for handoff. Pinterest acceptance and >10 scheduling remain unverified; production stays paused.

## CSV refresh — 2026-10-07

The approved source added Glide and ManyChat. Added strict vendor/board mappings so the current approved file parses without weakening unknown-host rejection. All 44 tests passed. Revalidated all ten ImageKit files and the Short.io redirect, then exported `pinterest-elevenlabs-pilot-v002.csv` at 2026-10-07 07:19:35 UTC. The first Pin has a blank date; the remaining nine run every 30 minutes from 07:49:35 through 11:49:35 UTC. Status is ready for manual upload; Pinterest acceptance and production activation remain pending.

## Validator corrections — 2026-10-07

The manual validator rejected repeated Link values and flagged the intentionally blank
first Publish date. Created ten deterministic Short.io paths, one per Pin, and verified
each first redirect against the exact approved ElevenLabs affiliate URL. Updated export
times to `:00`/`:30` UTC boundaries with zero seconds and at least 30 minutes before the
first scheduled row. All 48 tests passed. Exported `pinterest-elevenlabs-pilot-v003.csv`:
ten unique links, first row immediate, remaining rows 08:30–12:30 UTC.

## Explicit UTC correction — 2026-10-07

Pinterest rejected timestamps without an explicit UTC marker. Scheduled exports now use
`YYYY-MM-DDTHH:MM:SSZ`; all 48 tests pass. Live export revalidated all ten ImageKit PNGs
and all ten unique Short.io redirects, then created
`pinterest-elevenlabs-pilot-v004.csv`. The first row remains immediate; rows 2–10 are
scheduled from 09:30Z through 13:30Z on half-hour boundaries. The Short.io domain resolves
over public DNS/HTTPS and urlscan.io had no existing public result; Pinterest's private
link reputation remains verifiable only by import.

## Working template adopted — 2026-10-07

Compared the user-provided Looka CSV that Pinterest accepted. It uses seven exact
headers, no `Thumbnail`, no blank dates, and `YYYY-MM-DDTHH:MM:SS` timestamps without
`Z`; all times fall on `:00` or `:30`. Updated the exporter and tests to make this the
canonical format. All 48 tests passed. Live checks revalidated ten ImageKit files and
ten unique Short.io redirects, then created `pinterest-elevenlabs-pilot-v005.csv` with
ten scheduled rows from 10:00 through 14:30 UTC.

## Pin 02 blocked-link replacement — 2026-10-07

Pinterest identified `vettedsaasblueprint.s.gy/elevenlabs-pilot-02` as spam. Confirmed
the connected Short.io account owns the known-working `justonemedia.short.gy` domain,
then created `justonemedia.short.gy/elevenlabs-script-to-voice`. Verified the first hop
preserves the exact approved affiliate URL and the final ElevenLabs response is HTTP 200.
Updated only Pin 02, invalidated v005, and exported
`pinterest-elevenlabs-pilot-v006.csv`. It has ten unique links and no reference to the
blocked URL. All 52 tests passed; one transient remote disconnect occurred during live
export, and the clean retry succeeded after all ten assets passed individual checks.

## Full Short.io domain migration — 2026-10-07

User confirmed `justonemedia.short.gy` passes Pinterest. Created and verified ten unique
descriptive links on that domain, migrated every pilot Pin, and made it the default for
future link creation. `vettedsaasblueprint.s.gy` remains allowlisted only for historical
verification. All 53 tests passed. Exported `pinterest-elevenlabs-pilot-v007.csv` with
ten unique links, ten unique media URLs, no legacy-domain links, and scheduled rows from
11:00 through 15:30 UTC.

## Publishing boundary

User explicitly authorized agent upload of this ten-Pin pilot. Recurring 130-Pin batches remain manually uploaded and automation `prepare-pinterest-csv-batches` remains PAUSED until Pinterest pilot acceptance and scheduling beyond ten Pins are proven. Current browser account verified: Build With JustOneMedia.
