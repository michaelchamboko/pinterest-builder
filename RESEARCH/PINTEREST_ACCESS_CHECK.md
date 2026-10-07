---
title: "Pinterest Access Check"
tags: [pinterest, api, credentials]
status: active
created: 2026-09-17
---

## Verified result

- GET `https://api.pinterest.com/v5/user_account`: HTTP 401, Pinterest code 2, "Authentication failed."
- GET `https://api-sandbox.pinterest.com/v5/user_account`: HTTP 401, Pinterest code 2, "Authentication failed."
- No account identity or board could be verified. No write request was made and no Pin was created.
- Local token remained private; only sanitized response fields were emitted. The initial sandboxed shell could not reach the network; the authorized network retry reached both API hosts.
- The approved affiliate URL is present verbatim in the adjacent content strategy project's `approved-urls.md`: `https://try.elevenlabs.io/izj2b165mcsj`. Its final destination is not yet verified: the HTTP check failed. Verify the redirect before any publication.

## Next step

Update: the user subsequently confirmed the rejected value was the app secret, not an access token. It has been reclassified privately. Follow [PINTEREST_OAUTH_SETUP.md](PINTEREST_OAUTH_SETUP.md) for the current OAuth setup; the original diagnosis below records what was known at the time.

Generate a fresh access token for the intended environment and save it in `.env.local` as `PINTEREST_ACCESS_TOKEN`. A 401 alone does not establish whether the existing token is expired, invalid, or revoked, nor whether the app has Trial or Standard access. Re-run `rtk proxy python pinterest_check.py` after replacement.

For the requested flow, use `pins:write`, `boards:read`, and `pins:read`; the account identity check also needs `user_accounts:read`. `boards:write` is unnecessary unless creating or editing a board.

## Current official documentation

- [Access tiers](https://developer.pinterest.com/docs/key-concepts/access-tiers/): Trial-created Pins and boards are visible only to their creator as Sandbox entities. Standard supports normal publishing. Current account tier was not verified.
- [Sandbox](https://developer.pinterest.com/docs/developer-tools/sandbox/): Sandbox and production tokens are environment-specific. Sandbox board pagination may contain empty pages with a bookmark.
- [Create boards and Pins](https://developers.pinterest.com/docs/work-with-organic-content-and-users/create-boards-and-pins/).
- [Official API schema](https://github.com/pinterest/api-description/tree/main/v5).

## Approved Pin awaiting credentials

- Account: Build With JustOneMedia (`BuildWithJustOneMedia`).
- Board: AI Tools & Automation; ID remains unverified.
- Title: Turn Scripts into AI Voiceovers with ElevenLabs
- Description: #ad Affiliate link: I may earn a commission if you purchase through this link. Turn written scripts into AI voiceovers with ElevenLabs. Explore narration for tutorials, product explainers and social videos. Review the voice options and choose a plan with commercial rights before using audio for your business. Explore ElevenLabs through the link.
- Alt text: Black-and-white image of a woman wearing headphones at a laptop, with a coral audio waveform. Headline: Your script. A new voice. Text promotes AI voiceovers with ElevenLabs, with an Explore ElevenLabs call to action and affiliate disclosure.
- Destination: https://try.elevenlabs.io/izj2b165mcsj
- Image: `artifacts/ELEVENLABS_PIN.png`, visually inspected; includes the affiliate disclosure.
- On future successful creation, persist the returned Pin ID before verification. Do not retry a create request after an ambiguous response.
