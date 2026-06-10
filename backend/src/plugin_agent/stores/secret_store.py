from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from uuid import uuid4


class SecretStore:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.key_path = runtime_dir / "secret.key"
        if not self.key_path.exists():
            self.key_path.write_text(uuid4().hex)
        self.key = hashlib.sha256(self.key_path.read_text().encode("utf-8")).digest()

    def encrypt(self, value: str) -> str:
        raw = value.encode("utf-8")
        encrypted = bytes(byte ^ self.key[index % len(self.key)] for index, byte in enumerate(raw))
        return base64.urlsafe_b64encode(encrypted).decode("ascii")

    def decrypt(self, value: str) -> str:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        decrypted = bytes(byte ^ self.key[index % len(self.key)] for index, byte in enumerate(raw))
        return decrypted.decode("utf-8")
