from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel


ALLOWED_SUFFIXES = {
    ".pdf", ".txt", ".md", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".py", ".ipynb", ".csv", ".tsv",
}
GENERIC_MIME_TYPES = {"application/octet-stream", "binary/octet-stream"}


def validate_upload(name: str, content_type: str, content: bytes) -> None:
    safe_name = Path(name or "upload.bin").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported upload type: {suffix or 'missing extension'}")
    mime = content_type.split(";", 1)[0].strip().lower()
    if suffix == ".pdf":
        if mime not in {"application/pdf", *GENERIC_MIME_TYPES} or not content.startswith(b"%PDF-"):
            raise ValueError("PDF upload does not match its declared content type or signature")
        return
    allowed_application_types = {
        "application/json", "application/jsonl", "application/x-ndjson", "application/x-ipynb+json",
        "application/yaml", "application/x-yaml", "application/toml", "application/x-toml",
        "application/csv", "application/vnd.ms-excel", *GENERIC_MIME_TYPES,
    }
    if mime and not (mime.startswith("text/") or mime in allowed_application_types):
        raise ValueError(f"declared content type {mime!r} is not allowed for {suffix}")
    if b"\x00" in content:
        raise ValueError("text upload contains binary NUL bytes")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("text upload must be valid UTF-8") from exc
    if suffix in {".json", ".ipynb"}:
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{suffix} upload is not valid JSON") from exc
    if suffix == ".jsonl":
        try:
            for line in text.splitlines():
                if line.strip():
                    json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(".jsonl upload contains an invalid JSON record") from exc


class UploadRecord(BaseModel):
    id: str
    owner_id: str
    name: str
    content_type: str
    size: int
    sha256: str
    storage_path: str
    created_at: str

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "content_type": self.content_type,
            "size": self.size,
            "sha256": self.sha256,
            "content_url": f"/api/uploads/{self.id}/content",
            "created_at": self.created_at,
        }


class UploadRegistry:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.index_path = self.root / "uploads.json"
        self.records: dict[str, UploadRecord] = {}

    def load(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.records = {}
        if not self.index_path.exists():
            return
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.records = {key: UploadRecord.model_validate(value) for key, value in payload.items()}

    def create(self, owner_id: str, name: str, content_type: str, content: bytes) -> UploadRecord:
        upload_id = uuid4().hex
        safe_name = Path(name or "upload.bin").name
        validate_upload(safe_name, content_type or "application/octet-stream", content)
        owner_key = hashlib.sha256(owner_id.encode()).hexdigest()[:32]
        owner_root = self.root / owner_key
        owner_root.mkdir(parents=True, exist_ok=True)
        path = owner_root / upload_id
        path.write_bytes(content)
        record = UploadRecord(
            id=upload_id,
            owner_id=owner_id,
            name=safe_name,
            content_type=content_type or "application/octet-stream",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            storage_path=str(path.resolve()),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.records[upload_id] = record
        self._persist()
        return record

    def get_owned(self, upload_id: str, owner_id: str) -> UploadRecord:
        record = self.records.get(upload_id)
        if record is None:
            raise KeyError(upload_id)
        if record.owner_id != owner_id:
            raise PermissionError(upload_id)
        path = Path(record.storage_path)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(upload_id)
        return record

    def resolve_owned(self, upload_ids: list[str], owner_id: str) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for upload_id in upload_ids:
            record = self.get_owned(upload_id, owner_id)
            payload = record.model_dump(mode="json")
            excerpt = self._text_excerpt(record)
            if excerpt:
                payload["text_excerpt"] = excerpt
            resolved.append(payload)
        return resolved

    @staticmethod
    def _text_excerpt(record: UploadRecord) -> str:
        suffix = Path(record.name).suffix.lower()
        text_like = record.content_type.lower().startswith("text/") or suffix in {
            ".md", ".txt", ".json", ".jsonl", ".csv", ".tsv", ".py", ".toml", ".yaml", ".yml",
        }
        if not text_like:
            return ""
        raw = Path(record.storage_path).read_bytes()[:64 * 1024]
        return raw.decode("utf-8", errors="replace")[:12_000]

    def _persist(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {key: value.model_dump(mode="json") for key, value in self.records.items()}
        temporary = self.index_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, self.index_path)
