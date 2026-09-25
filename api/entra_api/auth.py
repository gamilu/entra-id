"""
Microsoft identity platform (v2.0) app-only auth for Microsoft Graph -
service-to-service, no signed-in user. Two real credential paths:

1. Client secret + client_credentials - simple, but Microsoft caps secret
   lifetime at 2 years max and explicitly recommends certificates for
   production workloads.
2. Client certificate + client_credentials (client_assertion) - the
   confidential-client app signs a short-lived JWT with its own RSA
   private key. Structurally similar to Okta's private_key_jwt, but
   Entra ID identifies *which* registered certificate to validate
   against via an `x5t` thumbprint in the JWT header, not a `kid` tied
   to a JWKS document - Microsoft never fetches a JWKS URL for this
   flow, the thumbprint alone has to match a certificate already
   uploaded to the App Registration.

Token endpoint: https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509 import load_pem_x509_certificate

GRAPH_DEFAULT_SCOPE = "https://graph.microsoft.com/.default"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _token_url(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def cert_thumbprint_x5t(certificate_pem: bytes) -> str:
    """
    SHA-1 thumbprint of the certificate's DER encoding, base64url-encoded
    - the `x5t` value Entra ID uses to look up which registered
    certificate a client assertion was signed with. SHA-1 here isn't a
    weakened choice; it's simply what the x5t header spec (and Entra ID's
    own certificate-thumbprint display in the Azure portal) uses as a
    certificate *identifier*, not as the signature algorithm itself - the
    assertion's actual signature is RS256.
    """
    cert = load_pem_x509_certificate(certificate_pem)
    der = cert.public_bytes(Encoding.DER)
    return _b64url(hashlib.sha1(der).digest())


def build_client_assertion(
    client_id: str,
    tenant_id: str,
    certificate_pem: bytes,
    private_key_pem: bytes,
    expires_in: int = 600,
) -> str:
    """
    Build and RS256-sign the JWT client assertion for Entra ID's
    certificate-credential client_credentials flow. Microsoft's
    documented guidance caps assertion lifetime well under the 1-hour
    ceiling other IdPs allow (Okta) - 10 minutes is the commonly cited
    safe default, so that's what this defaults to.
    """
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    token_url = _token_url(tenant_id)

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "x5t": cert_thumbprint_x5t(certificate_pem)}
    payload = {
        "iss": client_id,
        "sub": client_id,
        "aud": token_url,
        "iat": now,
        "nbf": now,
        "exp": now + expires_in,
        "jti": str(uuid.uuid4()),
    }

    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}"
        f".{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    signature = private_key.sign(
        signing_input.encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return f"{signing_input}.{_b64url(signature)}"


def client_secret_flow(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    scope: str = GRAPH_DEFAULT_SCOPE,
    timeout: int = 30,
) -> dict:
    """
    Simple app-only path: client_credentials with a client secret.
    `scope` defaults to Graph's `.default` scope, which tells Microsoft
    identity platform to use whatever Application permissions are
    already statically configured (and admin-consented) on this app's
    registration, rather than listing individual scopes per request -
    the standard pattern for app-only Graph calls.
    """
    response = requests.post(
        _token_url(tenant_id),
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def client_certificate_flow(
    tenant_id: str,
    client_id: str,
    certificate_pem: bytes,
    private_key_pem: bytes,
    scope: str = GRAPH_DEFAULT_SCOPE,
    timeout: int = 30,
) -> dict:
    """
    Full certificate-credential flow: build and sign the client
    assertion, POST client_credentials with client_assertion_type=
    jwt-bearer, return the token response.
    """
    assertion = build_client_assertion(client_id, tenant_id, certificate_pem, private_key_pem)

    response = requests.post(
        _token_url(tenant_id),
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "scope": scope,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
