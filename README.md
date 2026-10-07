# Pinterest CSV automation

Prepare batches locally; upload the final CSV to Pinterest yourself.
Production is **not activated** until the live pilot and bulk scheduling checks pass.

## Commands

Use the bundled Python runtime (includes Pillow):

```powershell
$PinPython = 'C:\Users\micha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
rtk proxy $PinPython -m unittest discover -v
rtk proxy $PinPython pinterest_batch.py init --batch elevenlabs-pilot --pilot
rtk proxy $PinPython pinterest_batch.py status --batch elevenlabs-pilot
rtk proxy $PinPython pinterest_batch.py pending --batch elevenlabs-pilot
```

Alternatively use Python 3.11+ with `pip install -r requirements.txt` in an isolated
environment. The core batch/CSV commands use only the standard library; live image
validation also needs Pillow.

The agent workflow is in [GUIDES/PINTEREST_BATCH_RUNBOOK.md](GUIDES/PINTEREST_BATCH_RUNBOOK.md).
New features and refactors follow [GUIDES/BUILD_WORKFLOW.md](GUIDES/BUILD_WORKFLOW.md).
The source of URL approval is the adjacent content strategy project's
`approved-urls.md`. No URLs or affiliate parameters are rewritten.

## Connection setup

1. ImageKit: the user-supplied `IMAGEKIT_PRIVATE_KEY` in `.env.local` has passed a
   read-only authentication check. The official key-based MCP and upload helper use
   this key. The earlier restricted OAuth route failed with `invalid_scope`.
2. Short.io: the supplied private key now passes domain-access checks. For future setup, create a private key with access to `justonemedia.short.gy` in
   [Integrations and API](https://app.short.io/settings/integrations/api-key), and save
   it after `SHORTIO_API_KEY=` in `.env.local`. Never paste the secret in chat.
3. Run `pinterest_services.py preflight --output .scratch/preflight.json` with the
   bundled Python. This verifies Short.io domain access and performs a bounded,
   authenticated ImageKit file read. Newly added MCP servers may
   require restarting Codex; the local API helper does not.

## Manual upload

Ask the agent to **prepare the upload-ready CSV for batch `<id>`** only when you
are ready to import. The agent rechecks media and links and then exports fresh dates.
Every Pin uses a distinct Short.io link and a 30-minute UTC slot aligned to `:00` or
`:30`, starting at least 30 minutes after export. Import promptly; delayed imports need
a newly timed export.
Upload only the latest validated version and only once. Keep the CSV as CSV when
opening it in Excel: do not save it as XLSX or change date formatting.

After Pinterest confirms the import, tell the agent the batch ID, how many Pins
were accepted, and whether their boards and dates are correct. Only then mark the
batch uploaded. If Pinterest partially accepted it, do not reimport all rows:
reconcile the accepted Pins first to avoid duplicates.

## Recovery

State lives in `batches/<id>/manifest.json`, with versioned exports alongside it.
`record` merges validated fields and invalidates review/evidence when its inputs
change. `resume --batch <id>` resumes a blocked batch after the blocker is fixed
and approval is rechecked. A leftover `.lock` requires checking that its recorded
process is no longer writing before removing that specific lock.

No code here creates a Pin, purchases services, or activates the schedule. Readiness
evidence is tracked in `readiness.local.json`; local tests never set live acceptance.
