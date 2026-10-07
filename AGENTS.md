# Repository Guidelines

## Structure and commands

- `pinterest_batch.py` manages batch state, approval checks, and record validation.
- `pinterest_services.py` verifies Short.io, public links, sources, and media.
- `pinterest_imagekit.py` uploads and reconciles ImageKit assets.
- `pinterest_export.py` verifies evidence and creates versioned CSVs.
- `test_*.py` contains the colocated `unittest` suite. `GUIDES/`, `PLANS/`,
  `RESEARCH/`, and `WORK_LOGS/` hold documentation. `batches/<id>/` is ignored
  local generated state.
- Use Python 3.11+ in an isolated environment:

  ```powershell
  python -m pip install -r requirements.txt
  python -m unittest discover -v
  python pinterest_batch.py status --batch <batch-id>
  python pinterest_export.py --batch <batch-id>
  ```

## Working rules

- Use four spaces, `snake_case`, `PascalCase` exceptions and test classes, and
  `UPPER_CASE` constants. Prefer small standard-library solutions and match
  surrounding code. Keep CLI errors concise and never expose credentials or raw
  secret-bearing responses.
- Use `unittest` and name tests `test_<behavior>`. Cover validation failures,
  retry-safe state changes, and exact CSV output. Run the full suite before
  declaring code changes complete. Live HTTP success does not prove Pinterest
  acceptance.
- Use imperative commit subjects. Every commit needs matching `Co-authored-by`
  and `Signed-off-by` trailers from the local Git identity. PRs describe behavior,
  validation, affected batches, and screenshots for visual changes.
- Before a new feature or shared workflow, use the
  [michaelchamboko/build-faster-skills `new-feature` workflow](https://github.com/michaelchamboko/build-faster-skills)
  and bundled `@Code Review`; never use Greploop. Follow
  [GUIDES/BUILD_WORKFLOW.md](GUIDES/BUILD_WORKFLOW.md) and its linked
  `code-structure` rules; run `unslop` on human-facing text.

## Pinterest invariants

- A default batch contains 100 Pins across ten products, 10 each: Carepatron,
  DataHawk, ElevenLabs, AdCreative.ai, Snowfire, Moosend, GetResponse, Flippa,
  Glide, and Manychat. Manychat's currently approved URL is its primary. If
  multiple Manychat URLs appear later, configuration must select one primary or
  fail explicitly.
- Codex plans, generates, reviews, and repairs content. Python enforces durable
  evidence gates. Review is bound to reviewed content and asset hashes. A
  nonempty verified subset may be `READY_PARTIAL`; systemic failures are
  `BLOCKED`. Close omissions after handoff and hold reservations until import
  outcome is known. See [GUIDES/PINTEREST_BATCH_RUNBOOK.md](GUIDES/PINTEREST_BATCH_RUNBOOK.md).
- Keep secrets in `.env.local`. Preserve approved affiliate URLs and tracking
  parameters exactly. Keep ImageKit and Short.io providers unchanged; use
  `justonemedia.short.gy` for new links. Pinterest uploads remain manual, with
  only the latest validated CSV imported once.
- Use the specified `michaelchamboko/marketingskills` fork when installed. Never
  silently install it. Report missing marketing capabilities.
