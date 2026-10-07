---
title: "Pinterest Multi-Product CSV Automation"
tags: [pinterest, automation, csv]
status: active
---

# Approved outcome

Prepare 100 Pins every three days at 21:00 Africa/Johannesburg: ten products,
ten Pins per product. The products are Carepatron, DataHawk, ElevenLabs,
AdCreative.ai, Snowfire, Moosend, GetResponse, Flippa, Glide, and Manychat.
Manychat's currently approved URL is its primary. If multiple Manychat URLs are
approved later, configuration must select one primary or fail explicitly.

The user imports the CSV manually. Codex plans, generates, reviews, and repairs
content; Python persists state and enforces evidence gates and CSV readiness.
Keep existing ImageKit and Short.io integrations and preserve every approved
affiliate URL and tracking parameter. The detailed operational contract is in
[GUIDES/PINTEREST_BATCH_RUNBOOK.md](../GUIDES/PINTEREST_BATCH_RUNBOOK.md).

# Production contract

- Cap each default batch at 100 Pins, 10 per listed product.
- Budget image generations at `ceil(1.2 * N)`, or 120 for 100 Pins.
- Allow at most three repair attempts for each Pin.
- Bind structured review to hashes of the exact source, copy, and assets. Changes
  invalidate review and dependent evidence.
- Allow a nonempty verified subset to reach `READY_PARTIAL`; systemic failures
  produce `BLOCKED`. Close omissions after handoff. Keep reservations through
  handoff until import outcome is known.
- Snapshot legacy state before migration. Do not treat legacy per-URL records or
  human-set review flags as new product-level evidence.
- Export the established seven-column schema with dates planned from the
  successful final export time in Africa/Johannesburg. Add a 30-minute buffer,
  round up to the next half-hour, and allocate one Pin per local slot from
  09:00 through 18:30 every day. Store `Publish Date` in UTC without a suffix.
  Reserve slots at CSV creation, consume them after whole-export upload
  confirmation, keep them reserved while unknown, and release them only after
  explicit whole-export cancellation. The user imports only the latest
  validated CSV manually.

# Marketing workflow

Use `michaelchamboko/marketingskills` when installed for product marketing,
copywriting, social content, ad creative, and copy editing. Do not install it
silently. Report missing capabilities and keep claims grounded in approved
product sources.

# Providers and acceptance evidence

Keep ImageKit for public media and `justonemedia.short.gy` for new Short.io
links. Use actual service responses for connection, upload, and redirect
evidence. Local tests or HTTP success do not prove Pinterest acceptance. The
producer does not publish through Pinterest browser or API automation.

# Legacy implementation record

Earlier records describe a 130-Pin, 13-URL proposal and an ElevenLabs pilot.
Treat their manifests and receipts as migration inputs only and snapshot them
before migration. Verify runtime behavior against the runbook before calling a
new batch ready. The initial ten-Pin pilot authorization does not authorize
agent uploads for recurring production.
