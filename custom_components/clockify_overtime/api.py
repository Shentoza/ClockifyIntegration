"""Clockify API client — pure async HTTP, no HA dependencies."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)


class ClockifyApiError(Exception):
    """Raised when the Clockify API returns an error or is unreachable."""


class ClockifyApi:
    """Async client for the Clockify REST API v1."""

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session
        self._headers = {
            "X-Api-Key": self._api_key,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def get_user_info(self) -> dict[str, Any]:
        """Return the logged-in user's profile (id, name, defaultWorkspace, …)."""
        return await self._request("GET", "/user")

    async def get_workspaces(self) -> list[dict[str, Any]]:
        """Return all workspaces the user belongs to."""
        return await self._request("GET", "/workspaces")

    async def get_projects(self, workspace_id: str) -> list[dict[str, Any]]:
        """Return all projects in a workspace (handles pagination)."""
        return await self._paginate(
            f"/workspaces/{workspace_id}/projects", page_size=50
        )

    async def get_time_entries(
        self,
        workspace_id: str,
        user_id: str,
        start: str,
        end: str,
    ) -> list[dict[str, Any]]:
        """Return all time entries for *user_id* between *start* and *end* (UTC ISO strings).

        Handles Clockify's pagination automatically (up to 500 entries per page).
        BREAK entries are included here — callers must filter them if needed.
        """
        return await self._paginate(
            f"/workspaces/{workspace_id}/user/{user_id}/time-entries",
            page_size=500,
            extra_params={"start": start, "end": end},
        )

    async def get_time_off_requests(
        self,
        workspace_id: str,
        user_id: str,
        start: str,
        end: str,
    ) -> list[dict[str, Any]]:
        """Return APPROVED time-off requests for *user_id* within [start, end].

        Falls back to an empty list if the endpoint is unavailable (free plan).
        The response shape is ``{"count": N, "requests": [...]}``.
        """
        try:
            result = await self._request(
                "POST",
                f"/workspaces/{workspace_id}/time-off/requests",
                json={
                    "start": start,
                    "end": end,
                    "statuses": ["APPROVED"],
                    "users": [user_id],
                },
            )
            if isinstance(result, dict):
                return result.get("requests", [])
            return []
        except ClockifyApiError as err:
            _LOGGER.debug("Time-off endpoint not available: %s", err)
            return []

    async def get_holidays_in_period(
        self,
        workspace_id: str,
        user_id: str,
        start: str,
        end: str,
    ) -> list[dict[str, Any]]:
        """Return holidays assigned to *user_id* within [start, end].

        Falls back to an empty list if the endpoint is unavailable (free plan).
        """
        try:
            result = await self._request(
                "GET",
                f"/workspaces/{workspace_id}/holidays/in-period",
                params={"assigned-to": user_id, "start": start, "end": end},
            )
            return result if isinstance(result, list) else []
        except ClockifyApiError as err:
            _LOGGER.debug("Holidays endpoint not available: %s", err)
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _paginate(
        self,
        endpoint: str,
        page_size: int = 50,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a list endpoint and return a flat list."""
        all_items: list[dict[str, Any]] = []
        page = 1
        while True:
            params: dict[str, Any] = {"page": page, "page-size": page_size}
            if extra_params:
                params.update(extra_params)
            items = await self._request("GET", endpoint, params=params)
            if not isinstance(items, list):
                break
            all_items.extend(items)
            if len(items) < page_size:
                break  # last page reached
            page += 1
        return all_items

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a single HTTP request and return the parsed JSON body."""
        url = f"{API_BASE_URL}{endpoint}"
        try:
            async with asyncio.timeout(15):
                response = await self._session.request(
                    method,
                    url,
                    headers=self._headers,
                    params=params,
                    json=json,
                )
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientResponseError as err:
            raise ClockifyApiError(
                f"HTTP {err.status} from {url}: {err.message}"
            ) from err
        except aiohttp.ClientError as err:
            raise ClockifyApiError(f"Connection error to {url}: {err}") from err
        except TimeoutError as err:
            raise ClockifyApiError(f"Timeout calling {url}") from err
