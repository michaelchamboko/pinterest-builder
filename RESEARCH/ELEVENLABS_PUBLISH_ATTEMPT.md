---
title: "ElevenLabs Pin Publication Attempt"
tags: [pinterest, publishing, oauth]
status: active
created: 2026-09-17
---

## Verified preflight

- Production OAuth authentication succeeded for `BuildWithJustOneMedia`, BUSINESS, business name Build With JustOneMedia.
- Public board `AI Tools & Automation`: ID `829718000039555889`, same owner, 49 Pins before submission.
- Approved destination `https://try.elevenlabs.io/izj2b165mcsj` returned HTTP 200 after redirects to `https://elevenlabs.io/` with affiliate tracking parameters. Python's default user agent received 403; curl with a browser user agent succeeded. The Pin request retained the original exact affiliate URL.
- Approved PNG, title, description, and alt text were submitted unchanged. Added supported AI disclosure `{"values":["AI_MODIFIED"]}`.

## Outcome

One `POST https://api.pinterest.com/v5/pins` was definitively rejected with HTTP 401, code 3, identifying `boards:write` as missing. No Pin ID was returned; no Pin was created. No retry was made.

The earlier statement that `boards:write` is needed only for board editing was incorrect. [Pinterest's current official OpenAPI](https://raw.githubusercontent.com/pinterest/api-description/main/v5/openapi.json), version 5.28.0, lists `boards:read`, `boards:write`, `pins:read`, and `pins:write` as Create Pin requirements. The live API error confirms this.

## Resume safely

The OAuth helper now requests `user_accounts:read,boards:read,boards:write,pins:read,pins:write`. Wait for user approval and verify the sanitized OAuth status and granted scopes.

The rejected request is preserved at `artifacts/ELEVENLABS_PUBLISH_RESULT.json`. `publish_elevenlabs.py` refuses to create when that file exists; the duplicate guard was verified offline. After new approval, archive this definitive rejection without deleting it, then perform one corrected create. Never repeat creation after an ambiguous result. Persist any successful returned Pin ID before verification.

Current app tier and public publishing capability remain unverified. A production read success does not establish Standard access.

## Corrected attempt: confirmed Trial access

After the user approved the corrected OAuth link, the saved token was verified to include all five required scopes. The original definitive rejection was preserved at `artifacts/ELEVENLABS_PUBLISH_REJECTED_MISSING_BOARDS_WRITE.json`.

One corrected production create request was sent. Pinterest rejected it with HTTP 403, code 29:

> Apps with Trial access may not create Pins in production https://api.pinterest.com - use API Sandbox https://api-sandbox.pinterest.com instead.

The current app is therefore confirmed to have Trial access. No Pin was created by either request, no Pin ID exists, and no ambiguous create was retried. The corrected rejection is retained at `artifacts/ELEVENLABS_PUBLISH_RESULT.json`.

Public API publishing requires Standard access for this app. The prepared asset and copy can instead be posted manually using Pinterest's normal publishing interface. A Sandbox test would be nonpublic and uses a separate Sandbox token; no Sandbox token has been obtained in this flow. No app upgrade submission or account change was performed.
