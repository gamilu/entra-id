"""
Microsoft Graph client for Entra ID (identity/directory) resources.

Base URL: https://graph.microsoft.com/v1.0/
Auth: Bearer token obtained via auth.client_secret_flow() or
auth.client_certificate_flow().

Pagination: OData @odata.nextLink - a full absolute URL in the response
body, carrying its own query string. Graph is OData v4 underneath, so
the standard "follow the link the server hands you back, don't
reconstruct it" rule applies.

Delta queries: Graph's higher-fidelity alternative to plain pagination
for change tracking. A delta query walks @odata.nextLink pages like any
other collection, but the *final* page returns an @odata.deltaLink
instead of a nextLink - persist that value, and passing it back in as
the next call's URL returns only what changed since, with no per-record
timestamp comparison or manual diffing required on the caller's side.

$batch: up to 20 sub-requests bundled into a single HTTP call
(POST /v1.0/$batch), each with its own id/method/url/body - a real
capability many REST APIs (Okta's included) don't offer.

Throttling: Graph returns 429 with a Retry-After header when a client
exceeds its request-rate budget. This client honors it with one bounded
retry rather than failing immediately or retrying blindly.
"""
from __future__ import annotations

import time
from typing import Iterator, Optional

import requests

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
MAX_BATCH_SIZE = 20
MAX_RETRY_AFTER_SECONDS = 60


class GraphClient:
    def __init__(self, access_token: str, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        })

    @property
    def _api_base(self) -> str:
        return GRAPH_BASE_URL

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        if response.status_code == 429:
            # Retry-After can be non-numeric (HTTP-date form) or
            # arbitrarily large; parse defensively and cap the sleep so
            # one throttled call can't stall a caller indefinitely. If
            # the cap is shorter than Graph wanted, the retry just 429s
            # again and raises - a visible failure, not a silent hang.
            try:
                retry_after = int(response.headers.get("Retry-After", "1"))
            except ValueError:
                retry_after = 1
            time.sleep(min(retry_after, MAX_RETRY_AFTER_SECONDS))
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response

    def get(self, path: str, params: Optional[dict] = None) -> requests.Response:
        url = f"{self._api_base}/{path.lstrip('/')}"
        return self._request("GET", url, params=params)

    def get_json(self, path: str, params: Optional[dict] = None):
        return self.get(path, params).json()

    def all_pages(self, path: str, params: Optional[dict] = None) -> Iterator[dict]:
        """Yield every record across all pages, following @odata.nextLink."""
        url = f"{self._api_base}/{path.lstrip('/')}"
        while url:
            payload = self._request("GET", url, params=params).json()
            params = None  # nextLink is a full absolute URL, already carrying its own query string
            yield from payload.get("value", [])
            url = payload.get("@odata.nextLink")

    def delta_query(
        self, path: str, delta_link: Optional[str] = None, params: Optional[dict] = None
    ) -> tuple[list[dict], Optional[str]]:
        """
        Returns (records, next_delta_link). Omit delta_link for an
        initial full sync; pass the delta_link a prior call returned to
        fetch only what changed since then. Persist next_delta_link
        between calls - it's the resumption token.
        """
        url = delta_link or f"{self._api_base}/{path.lstrip('/')}/delta"
        records: list[dict] = []
        next_delta_link: Optional[str] = None

        while url:
            payload = self._request("GET", url, params=params).json()
            params = None
            records.extend(payload.get("value", []))
            next_delta_link = payload.get("@odata.deltaLink")
            url = payload.get("@odata.nextLink")

        return records, next_delta_link

    def batch(self, requests_: list[dict]) -> dict[str, dict]:
        """
        POST /$batch with up to 20 sub-requests. Each item needs at
        least {"method": "GET", "url": "/users/{id}"} (url is relative
        to the v1.0 root, per Graph's batch convention); an "id" is
        assigned automatically if the caller doesn't supply one.
        Returns {id: response_dict} keyed the same way Graph's own
        `responses` array is - order in the response is not guaranteed
        to match request order, which is exactly why Graph uses ids
        instead of positional matching.
        """
        if not requests_:
            return {}
        if len(requests_) > MAX_BATCH_SIZE:
            raise ValueError(
                f"Graph $batch accepts at most {MAX_BATCH_SIZE} requests per call, "
                f"got {len(requests_)}"
            )

        body_requests = []
        for i, req in enumerate(requests_):
            item = dict(req)
            item.setdefault("id", str(i))
            body_requests.append(item)

        payload = self._request(
            "POST", f"{self._api_base}/$batch", json={"requests": body_requests}
        ).json()
        return {r["id"]: r for r in payload.get("responses", [])}

    # --- Users ---

    def list_users(self, **params) -> Iterator[dict]:
        yield from self.all_pages("users", params=params)

    def get_user(self, user_id: str) -> dict:
        return self.get_json(f"users/{user_id}")

    def create_user(self, body: dict) -> dict:
        return self._request("POST", f"{self._api_base}/users", json=body).json()

    def update_user(self, user_id: str, body: dict) -> None:
        """
        PATCH, not POST-to-the-same-resource - a real contrast with the
        sibling okta repo, where both create and update go through the
        same `/users` collection endpoint distinguished only by HTTP
        method-plus-path shape. Graph follows plain REST PATCH-for-
        partial-update semantics instead.
        """
        self._request("PATCH", f"{self._api_base}/users/{user_id}", json=body)

    def delete_user(self, user_id: str) -> None:
        self._request("DELETE", f"{self._api_base}/users/{user_id}")

    # --- Groups ---

    def list_groups(self, **params) -> Iterator[dict]:
        yield from self.all_pages("groups", params=params)

    def list_group_members(self, group_id: str) -> Iterator[dict]:
        yield from self.all_pages(f"groups/{group_id}/members")

    def add_group_member(self, group_id: str, member_object_id: str) -> None:
        """
        Graph models group membership as a navigation-property
        reference, not a plain PUT sub-resource the way Okta does
        (`PUT /groups/{id}/users/{id}`). Adding a member is a POST to
        the group's `members/$ref` endpoint, with the new member's full
        resource URL as the body's `@odata.id` - the same `$ref`
        convention Graph uses for every directory-object relationship,
        not something specific to groups.
        """
        url = f"{self._api_base}/groups/{group_id}/members/$ref"
        body = {"@odata.id": f"{self._api_base}/directoryObjects/{member_object_id}"}
        self._request("POST", url, json=body)

    def remove_group_member(self, group_id: str, member_object_id: str) -> None:
        url = f"{self._api_base}/groups/{group_id}/members/{member_object_id}/$ref"
        self._request("DELETE", url)

    # --- Applications / service principals ---
    # Real distinction worth preserving in the API surface, not just the
    # docs: an Application (app registration) is the global definition
    # of an app, one per home tenant; a ServicePrincipal is that app's
    # local identity within a specific tenant - permissions/consent are
    # evaluated against the service principal, not the registration.

    def list_applications(self, **params) -> Iterator[dict]:
        yield from self.all_pages("applications", params=params)

    def get_application(self, application_id: str) -> dict:
        return self.get_json(f"applications/{application_id}")

    def list_service_principals(self, **params) -> Iterator[dict]:
        yield from self.all_pages("servicePrincipals", params=params)
