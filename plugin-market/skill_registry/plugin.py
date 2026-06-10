from __future__ import annotations
from pathlib import Path

from plugin_agent_sdk import Plugin as PluginBase


class SkillRegistryPlugin(PluginBase):
    def start(self, kernel):
        super().start(kernel)
        self._skills = self._load_skills()

    def invoke(self, capability: str, payload: dict, context: dict) -> dict:
        if capability == "skill.list":
            return {"skills": [{"skill_id": key, "description": value["description"]} for key, value in sorted(self._skills.items())]}
        if capability == "skill.activate":
            return {"result": self._activate_skill(payload["name"])}
        if capability == "skill.read_file":
            return {"result": self._read_skill_file(payload["name"], payload["path"])}
        return super().invoke(capability, payload, context)

    def _load_skills(self) -> dict[str, dict]:
        loaded = {}
        for configured_dir in self.config.get("skill_dirs", []):
            directory = Path(configured_dir)
            if not directory.is_absolute():
                directory = self.plugin_dir / directory
            if not directory.exists():
                continue
            for file in sorted(directory.glob("*/SKILL.md")):
                parsed = self._parse_skill(file)
                loaded[parsed["skill_id"]] = parsed
        return loaded

    def _parse_skill(self, path: Path) -> dict:
        text = path.read_text(encoding="utf-8")
        metadata = {}
        content = text
        if text.startswith("---"):
            _, frontmatter, content = text.split("---", 2)
            for line in frontmatter.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()
        skill_id = metadata.get("name") or path.parent.name
        return {
            "skill_id": skill_id,
            "description": metadata.get("description", ""),
            "content": content.strip(),
            "path": str(path),
            "base_dir": str(path.parent),
        }

    def _activate_skill(self, name: str) -> dict:
        skill = self._skill_by_name(name)
        base_dir = Path(skill["base_dir"]).resolve()
        return {
            "name": skill["skill_id"],
            "description": skill.get("description", ""),
            "skill_file_path": skill.get("path", ""),
            "base_dir": str(base_dir),
            "files": self._list_skill_files(base_dir),
        }

    def _read_skill_file(self, name: str, relative_path: str) -> dict:
        skill = self._skill_by_name(name)
        base_dir = Path(skill["base_dir"]).resolve()
        normalized = self._assert_relative_skill_path(relative_path)
        target = (base_dir / normalized).resolve()
        if not self._is_inside(base_dir, target):
            raise ValueError("skill file path must stay inside the skill directory")
        stat = target.lstat()
        if target.is_symlink():
            raise ValueError("skill file path must stay inside the skill directory")
        if not target.is_file():
            raise ValueError(f"skill file is not a regular file: {normalized}")
        max_bytes = int(self.config.get("max_file_bytes", 512 * 1024))
        if stat.st_size > max_bytes:
            raise ValueError(f"skill file is too large to read: {normalized}")
        return {
            "skill": skill["skill_id"],
            "path": normalized,
            "file_path": str(target),
            "bytes": stat.st_size,
            "content": target.read_text(encoding="utf-8"),
        }

    def _skill_by_name(self, name: str) -> dict:
        skill = self._skills.get(str(name).strip())
        if not skill:
            raise ValueError(f"skill is not enabled for this agent: {name}")
        return skill

    def _list_skill_files(self, base_dir: Path) -> list[dict]:
        entries = []
        for path in sorted(base_dir.rglob("*")):
            stat = path.lstat()
            if path.is_symlink():
                continue
            relative = path.relative_to(base_dir).as_posix()
            if path.is_dir():
                entries.append({"path": relative, "type": "directory"})
            elif path.is_file():
                entries.append({"path": relative, "type": "file", "size": stat.st_size})
        return entries

    def _assert_relative_skill_path(self, value: str) -> str:
        normalized = str(value).strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or "\x00" in normalized:
            raise ValueError("invalid skill file path")
        segments = normalized.split("/")
        if any(segment in {"", ".", ".."} for segment in segments):
            raise ValueError("skill file path must stay inside the skill directory")
        return normalized

    def _is_inside(self, parent: Path, child: Path) -> bool:
        return child == parent or parent in child.parents
