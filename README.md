# entra-id

Personal reference repo + a working Python client library for **Entra
ID** (Microsoft's identity/directory platform, formerly Azure AD),
covering Microsoft Graph's app-only identity endpoints.

**Scope:** everything here is written from general platform knowledge
and Microsoft's own public developer documentation, plus general
identity-integration patterns from personal experience — expressed as
transferable patterns only. Nothing here is derived from, or contains,
source code, business logic, data, or configuration belonging to any
specific employer or institution. See `docs/integration-patterns.md`
for an honest scope note — adjacent Azure platform exposure (a prior
employer's Azure SQL data warehouse), not prior Entra ID
directory-administration experience specifically.

Microsoft Graph is OData v4 underneath, so pagination uses the standard
`@odata.nextLink` mechanism. What Graph adds *on top* of plain
pagination:

- **Delta queries** — `@odata.deltaLink` as a persisted resumption
  token for change tracking, instead of manual timestamp-diffing
- **`$batch`** — up to 20 sub-requests bundled into one HTTP call,
  matched back to the caller by `id` since response order isn't
  guaranteed to match request order

Also notable: **certificate-credential auth identified by an `x5t`
thumbprint header** rather than a JWKS-registered `kid` (see `okta`'s
JWT signing for the contrast), and a real **429/`Retry-After`**
throttling contract.

## Modules

- **`api/`** (`entra_api`) — `GraphClient`: Users/Groups/Applications
  CRUD, `@odata.nextLink` pagination, `delta_query()`, `batch()`,
  429/Retry-After handling; `client_secret_flow()` and
  `client_certificate_flow()` (real `x5t`-identified RS256 JWT signing,
  verified cryptographically the same way as `okta`'s)
- **`docs/integration-patterns.md`** — app-registration-vs-service-
  principal, admin-consent-as-operational-gate, certificate rotation,
  delta queries as the mechanism (not just the principle) behind
  `okta`'s "automate off events, not polling" rule

Each module's own `README.md` has usage examples and links to its
`docs/overview.md`. Pagination, delta-query resumption, batch
id-mapping, the `$ref` group-membership body shape, PATCH-vs-POST
update semantics, and 429/Retry-After handling are all tested against
synthetic fixtures. No live Entra ID tenant to test the HTTP-level
mechanics against yet.

**Requires:** `requests`, `cryptography`.
