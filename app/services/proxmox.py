# SPDX-License-Identifier: AGPL-3.0-only
import ssl
from pathlib import Path
from dotenv import dotenv_values
import httpx
from app.core.config import settings

class Proxmox:
    """Explicit VM operations; no deletion or forced stop in repair workflows."""
    def __init__(self):
        token = settings.proxmox_token.get_secret_value() if settings.proxmox_token else None
        if not token and settings.proxmox_token_file:
            path = Path(settings.proxmox_token_file)
            if path.stat().st_mode & 0o077:
                raise RuntimeError("Proxmox token file must have owner-only permissions")
            values = dotenv_values(path, interpolate=False)
            token_id, secret = values.get("token_id"), values.get("secret")
            if token_id and secret:
                token = token_id + "=" + secret
        if not settings.proxmox_url or not token:
            raise RuntimeError("Proxmox is not configured")
        if not settings.proxmox_url.startswith("https://"):
            raise RuntimeError("Proxmox requires HTTPS")
        tls = ssl.create_default_context(cafile=settings.proxmox_ca_file)
        self.client = httpx.Client(base_url=settings.proxmox_url.rstrip("/") + "/api2/json/", headers={"Authorization": "PVEAPIToken=" + token}, timeout=30, verify=tls)

    def request(self, node, vm_id, operation, method="GET"):
        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]+", node) or not isinstance(vm_id, int) or vm_id <= 0:
            raise ValueError("Invalid VM identity")
        response = self.client.request(method, f"nodes/{node}/qemu/{vm_id}/{operation}")
        response.raise_for_status()
        return response.json()["data"]

    def status(self, node, vm_id):
        return self.request(node, vm_id, "status/current")

    def start(self, node, vm_id):
        return self.request(node, vm_id, "status/start", "POST")

    def shutdown(self, node, vm_id):
        return self.request(node, vm_id, "status/shutdown", "POST")

    def guest_status(self, node, vm_id):
        return self.request(node, vm_id, "agent/ping", "POST")

    def close(self):
        self.client.close()
