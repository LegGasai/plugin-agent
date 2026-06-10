from __future__ import annotations

from pathlib import Path

from fastapi import Request


def is_multipart_request(request: Request) -> bool:
    return (request.headers.get("content-type") or "").lower().startswith("multipart/form-data")


async def write_multipart_upload(request: Request, temp_dir: Path) -> Path:
    form = await request.form()
    files: list[tuple[str, bytes]] = []
    relative_paths: list[str] = []
    for key, value in form.multi_items():
        if key == "files" and hasattr(value, "filename") and hasattr(value, "read"):
            filename = value.filename or "plugin-upload"
            files.append((filename, await value.read()))
        elif key == "relative_paths":
            relative_paths.append(str(value))
    if not files:
        raise ValueError("plugin package file is required")

    paths = relative_paths if len(relative_paths) == len(files) else [filename for filename, _ in files]
    if len(files) == 1 and "/" not in paths[0].replace("\\", "/"):
        upload_file = temp_dir / safe_upload_filename(paths[0])
        upload_file.write_bytes(files[0][1])
        return upload_file

    upload_root = temp_dir / "plugin-directory"
    for index, (_, payload) in enumerate(files):
        relative_path = safe_upload_relative_path(paths[index])
        destination = upload_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    first_segments = {Path(safe_upload_relative_path(path)).parts[0] for path in paths}
    if len(first_segments) == 1:
        candidate = upload_root / next(iter(first_segments))
        if (candidate / "plugin.yaml").exists():
            return candidate
    return upload_root


def safe_upload_filename(filename: str) -> str:
    safe_name = Path(filename.replace("\\", "/")).name
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("invalid upload filename")
    return safe_name


def safe_upload_relative_path(raw_path: str) -> Path:
    normalized = raw_path.replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"invalid upload path: {raw_path}")
    return Path(*parts)
