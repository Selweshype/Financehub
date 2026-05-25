"""Async Nordigen / GoCardless Bank Account Data API client.

All HTTP calls go through a shared httpx.AsyncClient that is created lazily
and reused across calls.  Token refresh is handled transparently.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

BASE_URL = "https://bankaccountdata.gocardless.com/api/v2"


class NordigenClient:
    """Thin async wrapper around the GoCardless Bank Account Data REST API."""

    def __init__(self, secret_id: str, secret_key: str) -> None:
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._access_token: str | None = None
        self._access_expires_at: int = 0
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    # ------------------------------------------------------------------ #
    # Token lifecycle
    # ------------------------------------------------------------------ #

    async def _get_new_tokens(self) -> dict[str, Any]:
        """Obtain a new access+refresh token pair from the Nordigen API."""
        resp = await self._client.post(
            "/token/new/",
            json={"secret_id": self._secret_id, "secret_key": self._secret_key},
        )
        resp.raise_for_status()
        return resp.json()

    async def _refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh an expired access token using the refresh token."""
        resp = await self._client.post(
            "/token/refresh/",
            json={"refresh": refresh_token},
        )
        resp.raise_for_status()
        return resp.json()

    async def ensure_token(
        self,
        access_token: str | None = None,
        access_expires_at: int = 0,
        refresh_token: str | None = None,
        refresh_expires_at: int = 0,
    ) -> dict[str, Any]:
        """Return valid token data, refreshing or re-obtaining as necessary.

        If *access_token* is still valid (>60 s margin) it is returned as-is.
        If the refresh token is valid, it is used to get a new access token.
        Otherwise a completely new token pair is obtained.
        """
        now = int(time.time())
        if access_token and access_expires_at - 60 > now:
            return {
                "access": access_token,
                "access_expires": access_expires_at - now,
                "refresh": refresh_token,
                "refresh_expires": refresh_expires_at - now,
            }

        if refresh_token and refresh_expires_at - 60 > now:
            data = await self._refresh_access_token(refresh_token)
            return {
                "access": data["access"],
                "access_expires": now + data.get("access_expires", 86400),
                "refresh": refresh_token,
                "refresh_expires": refresh_expires_at,
            }

        data = await self._get_new_tokens()
        return {
            "access": data["access"],
            "access_expires": now + data.get("access_expires", 86400),
            "refresh": data["refresh"],
            "refresh_expires": now + data.get("refresh_expires", 2592000),
        }

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    # ------------------------------------------------------------------ #
    # Institutions
    # ------------------------------------------------------------------ #

    async def list_institutions(
        self, access_token: str, country: str = "NL"
    ) -> list[dict[str, Any]]:
        """Return all institutions available for *country*."""
        resp = await self._client.get(
            "/institutions/",
            params={"country": country},
            headers=self._auth_headers(access_token),
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Requisitions (end-user bank connections)
    # ------------------------------------------------------------------ #

    async def create_requisition(
        self,
        access_token: str,
        institution_id: str,
        redirect_url: str,
        reference: str,
    ) -> dict[str, Any]:
        """Create a new requisition and return the Nordigen response."""
        resp = await self._client.post(
            "/requisitions/",
            json={
                "redirect": redirect_url,
                "institution_id": institution_id,
                "reference": reference,
            },
            headers=self._auth_headers(access_token),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_requisition(
        self, access_token: str, requisition_id: str
    ) -> dict[str, Any]:
        """Fetch a requisition by its Nordigen ID."""
        resp = await self._client.get(
            f"/requisitions/{requisition_id}/",
            headers=self._auth_headers(access_token),
        )
        resp.raise_for_status()
        return resp.json()

    async def delete_requisition(
        self, access_token: str, requisition_id: str
    ) -> None:
        """Delete (disconnect) a requisition."""
        resp = await self._client.delete(
            f"/requisitions/{requisition_id}/",
            headers=self._auth_headers(access_token),
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------ #
    # Account data
    # ------------------------------------------------------------------ #

    async def get_account_details(
        self, access_token: str, account_id: str
    ) -> dict[str, Any]:
        """Return account metadata (IBAN, bank name, etc.)."""
        resp = await self._client.get(
            f"/accounts/{account_id}/details/",
            headers=self._auth_headers(access_token),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_account_balances(
        self, access_token: str, account_id: str
    ) -> dict[str, Any]:
        """Return current balances for *account_id*."""
        resp = await self._client.get(
            f"/accounts/{account_id}/balances/",
            headers=self._auth_headers(access_token),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_account_transactions(
        self,
        access_token: str,
        account_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """Return booked and pending transactions for *account_id*.

        Optional ISO-8601 date range filters can be provided.
        """
        params: dict[str, str] = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        resp = await self._client.get(
            f"/accounts/{account_id}/transactions/",
            params=params,
            headers=self._auth_headers(access_token),
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Cleanup
    # ------------------------------------------------------------------ #

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
