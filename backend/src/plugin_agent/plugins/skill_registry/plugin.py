from __future__ import annotations

import re
from pathlib import Path

from plugin_agent_sdk import Plugin as PluginBase


class SkillRegistryPlugin(PluginBase):
    def start(self, kernel):
        super().start(kernel)
        self._skills = self._load_skills()

    def invoke(self, capability: str, payload: dict, context: dict) -> dict:
        if capability == "skill.list":
            return {"skills": [{"skill_id": key, "description": value["description"]} for key, value in sorted(self._skills.items())]}
        if capability == "skill.get":
            skill_id = payload["skill_id"]
            return {"skill": self._skills.get(skill_id, {"skill_id": skill_id, "description": "", "content": ""})}
        if capability == "skill.search":
            return {"skills": self._search_skills(payload["query"], payload.get("limit", 5))}
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
        return {"skill_id": skill_id, "description": metadata.get("description", ""), "content": content.strip(), "path": str(path)}

    def _search_skills(self, query: str, limit: int) -> list[dict]:
        terms = self._terms(query)
        scored = []
        for skill in self._skills.values():
            haystack = " ".join([skill["skill_id"], skill.get("description", ""), skill.get("content", "")]).lower()
            score = sum(haystack.count(term) for term in terms)
            if score > 0:
                scored.append({
                    "skill_id": skill["skill_id"],
                    "description": skill.get("description", ""),
                    "score": score,
                    "path": skill.get("path", ""),
                })
        return sorted(scored, key=lambda item: (-item["score"], item["skill_id"]))[:limit]

    def _terms(self, text: str) -> list[str]:
        return [term for term in re.split(r"\W+", text.lower()) if term]
