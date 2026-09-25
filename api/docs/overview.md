# Entra ID / Microsoft Graph — API Overview

Sources: [Microsoft Graph overview](https://learn.microsoft.com/en-us/graph/overview),
[Microsoft identity platform app-only access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/msal-acquire-cache-tokens#acquiretokenforclient),
[Certificate credentials](https://learn.microsoft.com/en-us/entra/identity-platform/certificate-credentials),
[Use delta query](https://learn.microsoft.com/en-us/graph/delta-query-overview),
[JSON batching](https://learn.microsoft.com/en-us/graph/json-batching),
[Microsoft Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling).

## Basics

- **Base URL:** `https://graph.microsoft.com/v1.0/`.
- **Responses:** JSON. Collections wrap results in a `value` array.

## Auth — app-only, two credential paths

Both go through the Microsoft identity platform v2.0 token endpoint:
`https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token`,
`grant_type=client_credentials`.

- **Client secret** — simplest path. Microsoft caps secret lifetime at
  2 years and explicitly recommends certificates for production
  workloads instead.
- **Client certificate (client_assertion)** — the app signs a
  short-lived JWT with its own RSA private key. Structurally similar to
  Okta's `private_key_jwt`, but the JWT **header** carries an `x5t`
  claim — the base64url SHA-1 thumbprint of the certificate's DER
  encoding — which is how Entra ID identifies *which* certificate
  already registered on the App Registration to validate the signature
  against. There's no JWKS URL fetch involved the way some IdPs do it;
  the thumbprint has to match a certificate uploaded ahead of time.
  Assertion claims: `iss`/`sub` = client_id, `aud` = the token endpoint
  URL, `exp` a short window (10 minutes is the commonly used default —
  notably tighter than Okta's 1-hour ceiling), `jti` unique. This
  library signs directly via `cryptography` (RS256) rather than
  wrapping a JWT library, and the signature is independently verified
  — including a tampered-payload rejection test — in this repo's
  verification suite.
- **Scope:** app-only calls typically use Graph's `.default` scope
  (`https://graph.microsoft.com/.default`), which tells the platform to
  use whatever Application permissions are already statically
  configured (and admin-consented) on the app registration, rather than
  listing individual scopes per request.

## Pagination

`@odata.nextLink` — a full absolute URL in the response body, already
carrying its own query string. Microsoft Graph is OData v4 underneath,
so the standard OData rule applies: "follow the link verbatim, don't
reconstruct query params yourself."

## Delta queries

A separate mechanism layered on top of plain pagination, for change
tracking. Call `GET /{resource}/delta` instead of the plain collection
endpoint; walk `@odata.nextLink` pages exactly like normal pagination,
but the **final** page returns `@odata.deltaLink` instead of a
`nextLink`. Persist that value — passing it back in as the next call's
URL returns only records that changed since, with no per-record
timestamp comparison needed.

## $batch

`POST /v1.0/$batch` bundles up to **20** sub-requests into one HTTP
call: `{"requests": [{"id": "1", "method": "GET", "url": "/users/123"}, ...]}`.
The response's `responses` array is **not guaranteed to preserve
request order** — each item echoes back the `id` it was submitted with,
and that id is the only reliable way to match a response to its
request. Okta's API, by comparison, has no equivalent.

## Throttling

429 responses carry a `Retry-After` header (seconds). This client
honors it with one bounded retry rather than failing immediately or
retrying blindly without backing off.

## Users / Groups / Applications

- **Users:** `/users`, `/users/{id}` — create is `POST`, but update is
  **`PATCH`**, not the same-endpoint `POST` Okta uses for both create
  and update.
- **Groups:** `/groups`, `/groups/{id}/members`. Membership changes go
  through the `$ref` navigation-property convention —
  `POST /groups/{id}/members/$ref` with body `{"@odata.id": ".../directoryObjects/{id}"}`
  to add, `DELETE /groups/{id}/members/{id}/$ref` to remove. This is
  the general pattern Graph uses for *any* directory-object
  relationship, not something groups-specific.
- **Applications / service principals:** `/applications` (app
  registrations, the global definition) and `/servicePrincipals` (the
  per-tenant local identity permissions are actually evaluated
  against) — kept as two distinct list operations in this client
  because conflating them is a real source of bugs in multi-tenant
  integrations (see `docs/integration-patterns.md`).
