"""
REST API client for unity.eopthome.no/api.

All endpoints follow /v1/ prefix and use Bearer token auth.
Serialization: JSON (Newtonsoft.Json on server side, standard json here).
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import httpx

from .auth import load_token, load_base_url


class SensioEoptAPIError(Exception):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"API error {status}: {body}")


class CloudClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
    ) -> None:
        self._base = (base_url or load_base_url()).rstrip("/")
        self._token = token or load_token()
        if not self._token:
            raise RuntimeError(
                "Not authenticated. Run `sensio_eopt login` first."
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, **params: Any) -> Any:
        url = self._base + path
        r = httpx.get(url, headers=self._headers(), params=params, timeout=15)
        if not r.is_success:
            raise SensioEoptAPIError(r.status_code, r.text)
        return r.json() if r.content else None

    def _post(self, path: str, body: Any = None) -> Any:
        url = self._base + path
        r = httpx.post(url, headers=self._headers(), json=body, timeout=15)
        if not r.is_success:
            raise SensioEoptAPIError(r.status_code, r.text)
        return r.json() if r.content else None

    # ------------------------------------------------------------------
    # Server / infrastructure
    # ------------------------------------------------------------------

    def get_version(self) -> dict:
        return self._get("/v1/server/version")

    def get_traffic_servers(self) -> list[dict]:
        data = self._get("/v1/trafficservers")
        return (data or {}).get("trafficServers", [])

    # ------------------------------------------------------------------
    # Projects / installations
    # ------------------------------------------------------------------

    def get_projects(self, user_id: str) -> list[dict]:
        data = self._get(f"/v1/users/{user_id}/projects")
        return data or []

    def get_project(self, project_id: str) -> dict:
        return self._get(f"/v1/projects/{project_id}")

    # ------------------------------------------------------------------
    # Controllers (hubs)
    # ------------------------------------------------------------------

    def get_controllers(self, project_id: str) -> list[dict]:
        """Return controllers for a project (contains LocalIp, TrafficServerHostAddress, etc.)"""
        data = self._get(f"/v1/projects/{project_id}/controllers")
        return data or []

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def get_devices(self, project_id: str) -> list[dict]:
        data = self._get(f"/v1/projects/{project_id}/devices")
        return data or []

    def get_device_status(self, device_id: str) -> dict:
        return self._get(f"/v1/devices/{device_id}/status")

    def send_device_event(self, device_id: str, event_type: str, value: Any = None) -> Any:
        body: dict[str, Any] = {}
        if value is not None:
            body["value"] = value
        return self._post(f"/v1/devices/{device_id}/events/{event_type}", body or None)

    # ------------------------------------------------------------------
    # Zones
    # ------------------------------------------------------------------

    def get_zone_children(self, zone_id: str) -> list[dict]:
        data = self._get(f"/v1/zones/{zone_id}/children")
        return data or []

    # ------------------------------------------------------------------
    # Functions / scenes
    # ------------------------------------------------------------------

    def trigger_function(self, project_id: str, fn_id: str, value: str = "1") -> Any:
        return self._post(f"/v1/projects/{project_id}/functions/{fn_id}/value/{value}")

    # ------------------------------------------------------------------
    # Alarms
    # ------------------------------------------------------------------

    def get_active_alarms(self) -> list[dict]:
        data = self._get("/v1/alarms/active")
        return data or []

    # ------------------------------------------------------------------
    # Token management (local controller credentials)
    # ------------------------------------------------------------------

    def create_device_token(
        self,
        device_id: str,
        client_type: str = "MAUI",
        device_name: str = "sensio-eopt-cli",
    ) -> dict:
        """Register this client and get a TokenId/TokenSecret for local TCP login."""
        body = {
            "deviceId": device_id,
            "deviceName": device_name,
            "clientType": client_type,
        }
        return self._post("/v1/tokens", body)

    # ------------------------------------------------------------------
    # User info
    # ------------------------------------------------------------------

    def get_current_user(self) -> dict:
        """Try common user-info paths."""
        for path in ("/v1/users/me", "/v1/users/current"):
            try:
                return self._get(path)
            except SensioEoptAPIError:
                continue
        raise SensioEoptAPIError(404, "user info endpoint not found")
