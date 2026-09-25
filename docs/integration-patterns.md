# Entra ID / Microsoft Graph — Integration Patterns

General identity-integration patterns applied to Entra ID specifically,
drawn from personal experience with SAML SSO and Azure AD-backed
provisioning automation (documented in the sibling `okta` repo's
`integration-patterns.md`), plus some adjacent Azure platform exposure
via a prior employer's Azure SQL data warehouse — not prior Entra ID
directory-administration experience specifically. Written as
transferable patterns, not tied to any employer's integration code or
configuration.

## App registration vs. service principal — the distinction that breaks multi-tenant integrations

Entra ID splits an application's identity into two separate objects,
and conflating them is a common source of "works in my tenant, breaks
in the customer's tenant" bugs:

- **App Registration** — the *global* definition of the application.
  Created once, in the app's home tenant. This is where the client
  ID/secret/certificate credentials live, and where the app's requested
  permissions are declared.
- **Service Principal** — the *local* instance of that app's identity
  within a given tenant. One is created automatically in the home
  tenant, and a new one is created in every other tenant that consents
  to use the app. Permissions and consent grants are evaluated against
  the service principal in the tenant actually being called, not
  against the app registration itself.

An integration that only ever runs in its own home tenant can get away
with never noticing this split. Anything built to be installed into
*other* organizations' tenants (a multi-tenant SaaS product, for
example) has to account for it explicitly — the same credentials work
everywhere, but the permission grant is per-tenant and has to be
verified (or triggered) separately for each one.

## Admin consent is an operational gate, not just a security control

Application permissions (the app-only permissions used with
`client_credentials`) require **admin consent**, granted explicitly by
a tenant administrator — an end user cannot consent to them the way
they can for delegated, sign-in-time permissions. Practically, this
means any onboarding flow for a new tenant needs an explicit step where
a tenant admin visits a consent URL, and the integration needs to
handle (and clearly surface, not silently swallow) the specific error
Microsoft returns when that step hasn't happened yet
(`AADSTS650053`/`AADSTS7000112`-class consent-required errors) rather
than treating it as a generic auth failure. Same underlying lesson as
`okta`'s auth-vs-provisioning separation: authentication succeeding
(the app got a token) doesn't mean authorization succeeded (the tenant
actually granted the permissions the app is trying to use).

## Certificates over secrets, and thumbprint-based rotation

Client secrets are capped at a 2-year maximum lifetime and Microsoft
explicitly steers production workloads toward certificate credentials
instead. The certificate-identification model (a JWT header carries the
signing certificate's SHA-1 thumbprint, `x5t` — see `api/entra_api/auth.py`)
has a genuine operational upside: **multiple certificates can be
registered on one App Registration at the same time**, each identified
by its own thumbprint. That enables zero-downtime rotation — register
the new certificate, start signing with
it, then remove the old one once nothing depends on it anymore, with no
window where the integration is unauthenticated.

## Delta queries: the mechanism, not just the principle

`okta`'s patterns doc states the general principle — automate off of
change events, not off of polling. Microsoft Graph is one of the few
platforms in this repo series that hands the *mechanism* for that
directly to the caller, rather than leaving it to be built on top: a
delta query returns a `@odata.deltaLink` representing "the state as of
this query." Persist it, and the next call using that exact link
returns only what changed since — no per-record `modifiedDateTime`
comparison, no manual diffing against a previous snapshot. The tradeoff
is that the delta token is opaque and single-use-per-resume — lose it,
and the only fallback is a full resync from scratch, so persisting it
durably (not just in memory) is not optional for anything running
unattended.
