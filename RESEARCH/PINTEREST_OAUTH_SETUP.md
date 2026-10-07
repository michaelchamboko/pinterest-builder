---
title: "Pinterest OAuth Setup"
tags: [pinterest, oauth, credentials]
status: active
created: 2026-09-17
---

## Corrected diagnosis

The user confirmed the earlier `PINTEREST_ACCESS_TOKEN` value was their app secret, not an access token. It was sent only to official Pinterest API endpoints. The app secret has been preserved under `PINTEREST_APP_SECRET`; the access-token field was cleared for OAuth acquisition. The earlier 401 response does not establish app access tier or compromised credentials.

## Configuration and flow

- User-provided App ID: `1544347`.
- User-provided registered callback: `http://localhost:3046/api/pinterest/callback` (exact match required).
- Local configuration: `.env.local`, excluded from Git.
- Requested scopes: `user_accounts:read,boards:read,boards:write,pins:read,pins:write`. The first approval omitted `boards:write`; the live Create Pin endpoint subsequently rejected the request with HTTP 401, code 3, explicitly identifying `boards:write` as missing. This verified requirement supersedes the earlier assumption that it was only needed for board edits.
- Helper: `pinterest_oauth.py`, Python standard library only. Binds only `127.0.0.1`, keeps random state in memory, rejects wrong/duplicate state, exchanges the code with Pinterest using HTTP Basic authentication, and follows no token-endpoint redirects.
- Approval link is generated only after binding the listener. It expires with the local helper after 15 minutes. Open the link on the same computer.
- Callback request URLs and codes are not logged. Tokens never appear in the browser page or status output.
- OAuth access token is saved in `.env.local`; the full response, including refresh token, is saved in `.pinterest-tokens.local.json`. Both are ignored. Do not display either file's contents in tool output.
- `.pinterest-oauth-status.local.json` contains safe progress, approval URL, and missing-scope names. `authorized` means token saved; it does not establish Standard app access or authorize further work automatically.
- Hidden helper stdout/stderr logs are ignored. Do not start a duplicate helper or stop another process occupying the callback port.
- No Pin publication occurs in this helper.

## Validation

`rtk proxy python -m unittest -v test_pinterest_oauth.py`: five tests passed, covering state rejection, user denial, confidential errors, token persistence preserving other configuration, and successful callbacks without exposing tokens.

The actual listener was tested with a synthetic invalid state: HTTP 400, status remained `waiting_for_approval`. Actual token exchange awaits user approval.

## Official references

- [Pinterest OAuth documentation](https://developer.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/): authorization-code flow, HTTP Basic token exchange, and scopes.
- [Connect app](https://developer.pinterest.com/docs/getting-started/connect-app/): redirect URI must exactly match registration.
- [Official quickstart](https://github.com/pinterest/api-quickstart): localhost callback support.
