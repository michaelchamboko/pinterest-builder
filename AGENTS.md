# Repository Guidelines

## Project Structure & Module Organization

- `pinterest_batch.py` owns batch state, approval checks, and record validation.
- `pinterest_services.py` handles Short.io, public-link, source, and media verification.
- `pinterest_imagekit.py` uploads and reconciles ImageKit assets.
- `pinterest_export.py` performs live verification before creating a versioned CSV.
- `test_*.py` files contain the colocated `unittest` suite.
- `GUIDES/`, `PLANS/`, `RESEARCH/`, and `WORK_LOGS/` hold project documentation.
- `batches/<batch-id>/` contains generated images, receipts, manifests, and exports; it is local generated state and is Git-ignored.

## Build, Test, and Development Commands

Use Python 3.11+ in an isolated environment:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -v
python pinterest_batch.py status --batch elevenlabs-pilot
python pinterest_export.py --batch elevenlabs-pilot
```

The test command runs all local tests. `status` is read-only. Run the networked, newly timed export immediately before upload.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` for functions and variables, `PascalCase` for exceptions and test classes, and `UPPER_CASE` for constants. Prefer standard-library solutions and small functions. Match surrounding code; no formatter or linter is configured. Keep CLI errors concise and never include credentials or raw secret-bearing responses.

## Testing Guidelines

Use `unittest`; name files `test_<module>.py` and methods `test_<behavior>`. Test validation failures, retry-safe state changes, and exact CSV output. Run the complete suite before declaring success. Live HTTP success does not prove Pinterest acceptance.

## Commit & Pull Request Guidelines

Use imperative subjects such as `Fix Pinterest publish dates`. Every commit must include matching `Co-authored-by` and `Signed-off-by` trailers from the repository's local Git identity. PRs should describe behavior, validation, affected batches, and screenshots for visual changes.

## Build Workflow

Before building a feature or shared workflow, follow [GUIDES/BUILD_WORKFLOW.md](GUIDES/BUILD_WORKFLOW.md). Apply the linked `code-structure` rules, use bundled `@Code Review` instead of Greploop, and run `unslop` on human-facing text.

## Marketing Copy Workflow

Use [Marketing Skills](https://github.com/coreyhaines31/marketingskills) for Pinterest titles, descriptions, keywords, and promotional variants. Install them with:

```powershell
npx skills add coreyhaines31/marketingskills --skill product-marketing copywriting copy-editing social ad-creative
```

Apply `product-marketing` first, then `copywriting`, `social`, `ad-creative`, and `copy-editing`. Ground claims in the destination, preserve the five-guide/five-promotion mix, and include affiliate disclosure.

## Security & Operational Safety

Keep secrets in `.env.local`; never commit or print them. Preserve approved affiliate URLs and tracking parameters exactly. `justonemedia.short.gy` is the required Short.io domain for every new link. Pinterest uploads remain manual, and only the latest validated CSV should be uploaded once.
