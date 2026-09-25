# api

Microsoft Graph client for Entra ID identity/directory resources,
`entra_api`.

```python
from entra_api import GraphClient, client_secret_flow, client_certificate_flow

# Simple path: client secret
token = client_secret_flow(tenant_id, client_id, client_secret)
client = GraphClient(token["access_token"])

# Recommended path for production: certificate credential (real x5t-identified RS256 JWT)
token = client_certificate_flow(tenant_id, client_id, certificate_pem, private_key_pem)
client = GraphClient(token["access_token"])

for user in client.list_users():
    print(user["displayName"])

# Incremental sync via delta query - no manual diffing
records, delta_link = client.delta_query("users")
```

- `entra_api/client.py` — `GraphClient`: Users/Groups/Applications CRUD,
  `all_pages()` following `@odata.nextLink` (standard OData
  pagination), `delta_query()` for change tracking,
  `batch()` for `$batch` request bundling (up to 20 per call), and
  429/`Retry-After` handling
- `entra_api/auth.py` — `client_secret_flow()` and
  `client_certificate_flow()` + `build_client_assertion()`: real
  RS256 JWT signing with an `x5t` certificate-thumbprint header
  (Entra ID's certificate-identification model — distinct from Okta's
  JWKS-based `kid` approach)
- `docs/overview.md` — auth (both paths), pagination, delta queries,
  batching, throttling, sourced from Microsoft's public Graph docs
- `examples/api_example.py` — runnable usage demos for both auth paths

Pagination, delta-query resumption, batch id-mapping, the `$ref`
group-membership body shape, PATCH-vs-POST update semantics, and
429/Retry-After handling are all verified against synthetic fixtures.
The JWT signing is verified **cryptographically** — a real RSA keypair
and self-signed certificate are generated, the `x5t` thumbprint is
independently recomputed and compared, the assertion is signed and its
signature independently checked against the public key, and a
tampered-payload negative test confirms rejection — not just checked
for producing a plausible-looking string. No live Entra ID tenant to
test the HTTP-level mechanics against yet.

**Requires:** `requests`, `cryptography`.
