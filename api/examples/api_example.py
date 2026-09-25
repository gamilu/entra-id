"""
Usage examples for entra_api.

Illustrative only - TENANT_ID/CLIENT_ID/credentials come from the
caller's own environment; no real tenant's data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entra_api import GraphClient, client_certificate_flow, client_secret_flow

TENANT_ID = os.environ["ENTRA_TENANT_ID"]
CLIENT_ID = os.environ["ENTRA_CLIENT_ID"]


def main_client_secret():
    """Simple path: client secret."""
    token = client_secret_flow(TENANT_ID, CLIENT_ID, os.environ["ENTRA_CLIENT_SECRET"])
    client = GraphClient(token["access_token"])

    for user in client.list_users(**{"$select": "id,displayName,mail"}):
        print(user["displayName"], user.get("mail"))


def main_client_certificate():
    """Recommended path for production: certificate credential."""
    with open(os.environ["ENTRA_CERT_PATH"], "rb") as f:
        certificate_pem = f.read()
    with open(os.environ["ENTRA_KEY_PATH"], "rb") as f:
        private_key_pem = f.read()

    token = client_certificate_flow(TENANT_ID, CLIENT_ID, certificate_pem, private_key_pem)
    client = GraphClient(token["access_token"])

    # Incremental sync: first call with no delta_link does a full pass
    # and hands back a resumption token to persist.
    records, delta_link = client.delta_query("users")
    print(f"Full sync: {len(records)} users. Persist delta_link for next run:")
    print(delta_link)

    # A later run resumes from the persisted token - only changes since:
    # changed_records, delta_link = client.delta_query("users", delta_link=saved_delta_link)

    # Batch several lookups into one HTTP call:
    results = client.batch([
        {"method": "GET", "url": "/users/alice@example.com"},
        {"method": "GET", "url": "/users/bob@example.com"},
    ])
    for req_id, response in results.items():
        print(req_id, response["status"])

    client.add_group_member("00g1exampleGroupId", "00u1exampleUserId")


if __name__ == "__main__":
    main_client_secret()
