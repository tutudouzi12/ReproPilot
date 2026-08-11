from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.benchmark import profile_dataset
from app.models import PlanRequest
from app.uploads import UploadRegistry, validate_upload


def test_upload_type_validation_checks_extension_mime_and_content_signature():
    validate_upload("notes.md", "text/markdown", "可信笔记".encode())
    validate_upload("paper.pdf", "application/pdf", b"%PDF-1.7\n")
    validate_upload("records.jsonl", "application/json", b'{"x":1}\n{"x":2}\n')

    with pytest.raises(ValueError, match="unsupported"):
        validate_upload("payload.exe", "application/octet-stream", b"MZ")
    with pytest.raises(ValueError, match="signature"):
        validate_upload("paper.pdf", "application/pdf", b"not a pdf")
    with pytest.raises(ValueError, match="invalid JSON"):
        validate_upload("records.jsonl", "application/json", b"not-json\n")


def test_upload_registry_uses_hashed_owner_directory_and_opaque_storage_name(tmp_path):
    registry = UploadRegistry(tmp_path / "uploads")
    record = registry.create("owner@example.com", "private notes.md", "text/markdown", b"notes")
    expected_owner = hashlib.sha256(b"owner@example.com").hexdigest()[:32]

    stored = Path(record.storage_path)
    assert stored.parent.name == expected_owner
    assert stored.name == record.id
    assert "private notes.md" not in record.storage_path
    assert registry.get_owned(record.id, "owner@example.com").sha256 == record.sha256
    with pytest.raises(PermissionError):
        registry.get_owned(record.id, "other-owner")


def test_opaque_storage_path_preserves_dataset_format_from_public_name(tmp_path):
    registry = UploadRegistry(tmp_path / "uploads")
    content = b"review,label\ngood,positive\n"
    record = registry.create("owner", "reviews.csv", "text/csv", content)

    manifest = profile_dataset({"uploaded_files": [record.model_dump(mode="json")]})

    assert Path(record.storage_path).suffix == ""
    assert manifest.format == "csv"


def test_plan_request_enforces_backend_attachment_limit():
    with pytest.raises(ValidationError):
        PlanRequest(intent="analyze", attachments=[f"upload-{index}" for index in range(9)])
