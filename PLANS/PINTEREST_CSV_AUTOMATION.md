---
title: "Pinterest CSV Automation Implementation"
tags: [pinterest, automation, csv]
status: active
created: 2026-09-17
---

# Agreed outcome

Prepare 130 Pins every three days at 21:00 Africa/Johannesburg on this computer.
The exact 13 approved URLs each receive five visual guides and five promotional
images. Read the adjacent `Vetted SaaS B - Content Strategy and Growth Strategy/approved-urls.md`
before every batch and export. The two DataHawk tracking URLs remain separate.
The user manually uploads the CSV. No Pinterest API/browser publishing is authorized
as part of the automated producer.

Use built-in Codex image generation, 2:3 PNG/JPEG images, affiliate disclosure,
and grounded product claims. Upload to ImageKit under
`/pinterest/<batch-id>/<vendor-and-url-id>/`. Use `justonemedia.short.gy` for new
Short.io links, preserving each exact original affiliate URL. Keep
`vettedsaasblueprint.s.gy` allowlisted only for legacy receipt verification.

# Export contract

Match the proven working Looka template exactly: seven headers named `Title`,
`Media URL`, `Pinterest Board`, `Description`, `Link`, `Publish Date`, and `Keywords`.
Do not add a Thumbnail column. Keep titles <=100 characters and descriptions <=500
characters with disclosure; use relevant comma-separated Keywords.
Public media file URLs, no authentication. Board mapping lives in
`pinterest_batch.py`. Interleave vendors. Export on user request only. Schedule every
row in UTC using `YYYY-MM-DDTHH:MM:SS` without a suffix, aligned to `:00` or `:30`,
starting at least 30 minutes after export. Version exports; never overwrite or reimport
a previously uploaded batch. Regenerate timestamps before a delayed import.

# Evidence gate

Connect and verify ImageKit and Short.io before generating a ten-Pin ElevenLabs
pilot. User imports the pilot and confirms acceptance and dates. Then verify bulk
scheduling beyond ten Pins before activating a production cadence anchored to the
first production run. Local passing tests do not establish live Pinterest acceptance.

# Implementation ledger

- Ruling: the requested folder is now a Git repository on `main`, with
  `https://github.com/michaelchamboko/pinterest-builder.git` as `origin`.
- Ruling: use a deterministic local Python state/CSV runner and agent instructions
  for built-in image generation. A Python process cannot directly call Codex's
  conversation-only image tool. No paid image API substitution is authorized.
- Ruling: store the Short.io secret locally and reference it through a launcher;
  never store a literal key in Codex arguments, source, or logs.
- ImageKit restricted OAuth failed; the user supplied a private API key instead.
  Official key-based MCP and local upload helper are configured; live reads and uploads pass.
- Short.io supplied key verified for `justonemedia.short.gy`. Ten pilot images uploaded
  with durable receipts and original-byte public delivery checks; 62 local tests pass.
- User authorized agent submission of the initial ten-Pin pilot. Production uploads remain manual.
- Core owner: batch_core. Service helpers owner: service_helpers.
  Independent review: core_review. Root owns integration, docs, and release evidence.

# Sources

- https://help.pinterest.com/en/business/article/bulk-upload-video-pins
- https://help.pinterest.com/en/business/article/schedule-pins
- https://imagekit.io/docs/build-with-ai
- https://docs.short.io/articles/integrations-and-extensions/direct-integrations/how-to-integrate-and-use-short.io-with-your-mcp-enabled-service
- https://developers.short.io/reference/post_links
