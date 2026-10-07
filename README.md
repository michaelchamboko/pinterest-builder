# Pinterest CSV automation

Prepare 100 Pins across ten products every three days at 21:00
Africa/Johannesburg: Carepatron, DataHawk, ElevenLabs, AdCreative.ai, Snowfire,
Moosend, GetResponse, Flippa, Glide, and Manychat, with ten Pins per product.
Manychat's currently approved URL is its primary; if more than one is approved
later, configuration must select one or fail. The user imports validated CSVs
manually.

## Commands

Use Python 3.11+ in an isolated environment:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -v
python pinterest_batch.py status --batch <batch-id>
python pinterest_export.py --batch <batch-id>
```

See [GUIDES/PINTEREST_BATCH_RUNBOOK.md](GUIDES/PINTEREST_BATCH_RUNBOOK.md) for
batch production, evidence gates, migration, reservations, export, and import
reconciliation. New feature work follows [GUIDES/BUILD_WORKFLOW.md](GUIDES/BUILD_WORKFLOW.md).

## Providers and secrets

Keep using ImageKit for media and `justonemedia.short.gy` for new Short.io
links. Store credentials in `.env.local`; never paste or print secrets. Preserve
approved affiliate URLs and tracking parameters. Use the
`michaelchamboko/marketingskills` fork when installed. Do not silently install
it; report missing capabilities.

## Manual import

Request an upload-ready CSV when ready to import. Use only the latest validated
file and import it once. Report accepted counts and any partial or ambiguous
outcome so accepted Pins can be reconciled before another import.
