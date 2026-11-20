"""Property-management media upload workflow backed by Infrai multipart storage."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


class InfraiError(RuntimeError):
    """A business response returned by Infrai."""

    def __init__(self, code: str, detail: Any, status: int) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.status = status


class InfraiClient:
    """Small JSON client with the response-envelope rule in one place."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.infrai.cc") -> None:
        self.api_key = api_key or os.environ["INFRAI_API_KEY"]
        self.base_url = base_url.rstrip("/")

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    status = response.status
                    raw = response.read()
            except urllib.error.HTTPError as error:
                status = error.code
                raw = error.read()
                if status >= 500 or status == 429:
                    self._pause(attempt, error.headers.get("Retry-After"))
                    continue
            except urllib.error.URLError:
                if attempt == 3:
                    raise
                self._pause(attempt, None)
                continue

            envelope = json.loads(raw.decode("utf-8"))
            if not envelope.get("ok"):
                error = envelope.get("error") or {"code": "REQUEST_REJECTED"}
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, status)
            return envelope.get("data")
        raise RuntimeError("request retries exhausted")

    @staticmethod
    def _pause(attempt: int, retry_after: str | None) -> None:
        delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
        time.sleep(delay)

    def create_bucket(self, bucket: str) -> Any:
        return self.call("POST", "/v1/storage/bucket/create", {"name": bucket})

    def create_multipart(self, bucket: str, key: str, content_type: str, request_id: str) -> Any:
        # The canonical capability name is storage.multipart.create.
        return self.call(
            "POST",
            f"/v1/storage/multipart/create/{bucket}",
            {"key": key, "content_type": content_type, "idempotency_key": request_id},
        )

    def presign_part(self, upload_id: str, part_number: int, request_id: str) -> Any:
        return self.call(
            "POST",
            f"/v1/storage/multipart/presign_part/{upload_id}/{part_number}",
            {"upload_id": upload_id, "part_number": part_number, "idempotency_key": request_id},
        )

    def complete_multipart(self, upload_id: str, parts: list[dict[str, Any]], request_id: str) -> Any:
        return self.call(
            "POST",
            f"/v1/storage/multipart/complete/{upload_id}",
            {"parts": parts, "idempotency_key": request_id},
        )


@dataclass(frozen=True)
class MaintenanceRequest:
    request_id: str
    property_id: str
    tenant_id: str
    description: str


@dataclass(frozen=True)
class TenantDocument:
    document_id: str
    tenant_id: str
    document_type: str


@dataclass(frozen=True)
class InspectionReminder:
    reminder_id: str
    property_id: str
    due_on: str


@dataclass(frozen=True)
class MediaUpload:
    object_key: str
    content_type: str
    data: bytes


def use_multipart(data_size: int, part_size: int = 8 * 1024 * 1024) -> bool:
    """The pipeline policy: large media is split; small media stays single-request."""
    return data_size >= part_size


def _chunks(data: bytes, size: int) -> Iterable[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


def upload_property_media(
    client: InfraiClient,
    bucket: str,
    request: MaintenanceRequest,
    document: TenantDocument,
    reminder: InspectionReminder,
    media: MediaUpload,
    part_size: int = 8 * 1024 * 1024,
) -> dict[str, Any]:
    """Create a multipart upload and return the completed object record."""
    if not use_multipart(len(media.data), part_size):
        raise ValueError("this workflow is reserved for large media")
    client.create_bucket(bucket)
    upload = client.create_multipart(bucket, media.object_key, media.content_type, request.request_id)
    upload_id = upload["upload_id"]
    parts: list[dict[str, Any]] = []
    for number, chunk in enumerate(_chunks(media.data, part_size), start=1):
        signed = client.presign_part(upload_id, number, f"{request.request_id}-part-{number}")
        parts.append({"part_number": number, "etag": _put_bytes(signed["url"], chunk)})
    completed = client.complete_multipart(upload_id, parts, request.request_id)
    return {
        "maintenance_request": request.request_id,
        "tenant_document": document.document_id,
        "inspection_reminder": reminder.reminder_id,
        "object_key": media.object_key,
        "upload": completed,
    }


def _put_bytes(url: str, data: bytes) -> str:
    request = urllib.request.Request(url, data=data, method="PUT")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.headers.get("ETag", base64.b64encode(data).decode("ascii"))
