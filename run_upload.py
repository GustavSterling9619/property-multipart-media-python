"""Runnable command: upload one local inspection video."""

import argparse
from pathlib import Path

from src.property_media_upload import (
    InfraiClient,
    InspectionReminder,
    MaintenanceRequest,
    MediaUpload,
    TenantDocument,
    upload_property_media,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload property inspection media in parts")
    parser.add_argument("path", type=Path)
    parser.add_argument("--bucket", default="property-media")
    args = parser.parse_args()
    data = args.path.read_bytes()
    result = upload_property_media(
        InfraiClient(),
        args.bucket,
        MaintenanceRequest("mr-100", "building-7", "tenant-42", "leaking valve"),
        TenantDocument("doc-42", "tenant-42", "lease"),
        InspectionReminder("inspect-100", "building-7", "2026-11-01"),
        MediaUpload(f"inspection/{args.path.name}", "video/mp4", data),
    )
    print(result)


if __name__ == "__main__":
    main()
