"""Opt-in update checks backed by a signed release manifest."""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str = ""


def _version(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().lstrip("v").split("."))
    except ValueError:
        return (0,)


def check_for_update(current_version: str, timeout: float = 10.0) -> UpdateInfo | None:
    """Fetch and verify the configured Ed25519-signed JSON manifest."""
    manifest_url = os.environ.get("PTFANALYZER_UPDATE_MANIFEST_URL", "").strip()
    public_key = os.environ.get("PTFANALYZER_UPDATE_PUBLIC_KEY", "").strip()
    if not manifest_url or not public_key:
        raise RuntimeError("The signed update channel is not configured.")
    request = urllib.request.Request(manifest_url, headers={"User-Agent": f"PTFAnalyzer/{current_version}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"Update server returned HTTP {response.status}.")
        payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
    fields = {key: str(payload.get(key, "")) for key in ("version", "url", "sha256")}
    if not all(fields.values()) or not fields["url"].lower().startswith("https://"):
        raise RuntimeError("The update manifest is incomplete or uses a non-HTTPS URL.")
    signed = "|".join(fields[key] for key in ("version", "url", "sha256")).encode("utf-8")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(
            base64.b64decode(str(payload.get("signature", ""))), signed
        )
    except Exception as exc:
        raise RuntimeError("The update manifest signature is invalid.") from exc
    if _version(fields["version"]) <= _version(current_version):
        return None
    return UpdateInfo(fields["version"], fields["url"], fields["sha256"], str(payload.get("notes", "")))
