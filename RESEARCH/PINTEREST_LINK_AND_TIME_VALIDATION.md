---
title: "Pinterest Link and Time Validation"
tags: [pinterest, shortio, scheduling]
status: active
created: 2026-10-07
---

Pinterest's official bulk-upload guide accepts a future UTC timestamp formatted like
`2023-12-17T08:00:00`. It does not document a restriction to `:00` or `:30` minutes.
Source: https://help.pinterest.com/en/business/article/bulk-upload-video-pins

The user-required cadence now aligns every scheduled row to `:00` or `:30` with zero
seconds. Following a Pinterest import failure, exports now add an explicit `Z` suffix
to remove timezone ambiguity. The first row remains blank for immediate publication,
as Pinterest explicitly documents.

Pilot validation rejected repeated Link values within the same CSV. Short.io documents
that supplying a custom `path` creates a new short URL even when the same `originalURL`
already exists, and an existing path with the same original returns that link. This
supports deterministic retry-safe per-Pin paths while preserving the exact affiliate
destination. Source: https://developers.short.io/reference/post_links

On 2026-10-07, `vettedsaasblueprint.s.gy` resolved publicly over DNS and HTTPS. All ten
pilot links redirected to the exact approved ElevenLabs affiliate URL during live export.
A read-only urlscan.io search returned zero existing public scan results. That absence is
not a clean verdict, and no public service can reveal Pinterest's private domain trust
state. Pinterest says it may block links that redirect, are broken, misleading, spammy,
unsafe, or violate its policies. Source: https://help.pinterest.com/en/article/suspicious-links

The user then supplied a known-working Pinterest export:
`Pinterest_Bulk_Upload_UNIFIED_Looka_20260218_132801.csv`. Its 24 accepted rows use
seven columns, omit `Thumbnail`, schedule every row, and format UTC dates as
`YYYY-MM-DDTHH:MM:SS` without `Z`. It is UTF-8 without a BOM and uses CRLF line endings.
This proven file supersedes the earlier eight-column and explicit-`Z` assumptions for
future exports.

Pinterest reported `https://vettedsaasblueprint.s.gy/elevenlabs-pilot-02` as spam.
The connected Short.io account also owns `justonemedia.short.gy`, the domain used by
the proven Looka export. Pin 02 now uses
`https://justonemedia.short.gy/elevenlabs-script-to-voice`. Live verification confirms
its first redirect is the exact approved ElevenLabs affiliate URL and its final response
is HTTP 200. Pinterest acceptance still requires an import test.

After the replacement domain passed Pinterest's link check, all ten pilot links were
migrated to unique descriptive paths on `justonemedia.short.gy`. The legacy domain
remains accepted by local validation only so historical receipts can still be checked;
new links default to `justonemedia.short.gy`.
