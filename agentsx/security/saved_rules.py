"""Persistent security rules — "always allow" / "always deny" storage.

Rules are saved as JSON in ``~/.agentsx/saved_rules.json`` so that
the user only needs to approve a tool+path combination once.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentsx.protocol.messages import Decision

logger = logging.getLogger(__name__)

_DEFAULT_RULES_PATH = Path.home() / ".agentsx" / "saved_rules.json"


@dataclass
class SavedRule:
    """A persisted security rule.

    Attributes:
        action: Tool name or glob pattern (e.g. ``"tool_file_write"``).
        resource: Resource path glob (e.g. ``"/tmp/*"`` or ``"*"``).
        effect: Decision to apply (ALLOW or FORBIDDEN).
        note: Optional human-readable note.
    """

    action: str
    resource: str
    effect: Decision
    note: str = ""

    def matches(self, tool_name: str, path: str) -> bool:
        """Check if this rule matches a specific tool+path."""
        from fnmatch import fnmatch

        return fnmatch(tool_name, self.action) and fnmatch(path, self.resource)

    def to_dict(self) -> dict[str, str]:
        """Serialize to a JSON-compatible dict."""
        return {
            "action": self.action,
            "resource": self.resource,
            "effect": self.effect.value,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SavedRule":
        """Deserialize from a dict."""
        return cls(
            action=str(data.get("action", "*")),
            resource=str(data.get("resource", "*")),
            effect=Decision(str(data.get("effect", Decision.PROMPT.value))),
            note=str(data.get("note", "")),
        )


class SavedRulesStore:
    """Persistent store for user-approved/denied tool+path rules.

    Rules are stored as a JSON file under ``~/.agentsx/``.

    Usage::

        store = SavedRulesStore()
        store.add("tool_file_write", "/tmp/build/*", Decision.ALLOW, note="build dir")
        rules = store.list()
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_RULES_PATH
        self._rules: list[SavedRule] = self._load()

    def _load(self) -> list[SavedRule]:
        """Load rules from disk."""
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return []
            return [SavedRule.from_dict(item) for item in raw]
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load saved rules from %s: %s", self._path, exc)
            return []

    def _save(self) -> None:
        """Persist rules to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [rule.to_dict() for rule in self._rules]
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def add(
        self,
        action: str,
        resource: str,
        effect: Decision = Decision.ALLOW,
        note: str = "",
    ) -> SavedRule:
        """Add a new rule and persist it.

        Args:
            action: Tool name or glob pattern.
            resource: Resource path glob.
            effect: Decision to apply.
            note: Optional human-readable note.

        Returns:
            The newly created rule.
        """
        rule = SavedRule(action=action, resource=resource, effect=effect, note=note)
        self._rules.append(rule)
        self._save()
        return rule

    def remove(self, index: int) -> bool:
        """Remove a rule by index and persist.

        Returns:
            True if removed, False if index out of range.
        """
        if 0 <= index < len(self._rules):
            self._rules.pop(index)
            self._save()
            return True
        return False

    def list(self) -> list[SavedRule]:
        """Return a copy of all saved rules."""
        return list(self._rules)

    def clear(self) -> None:
        """Remove all saved rules."""
        self._rules.clear()
        self._save()

    def evaluate(
        self,
        tool_name: str,
        path: str = "",
    ) -> Decision | None:
        """Evaluate tool+path against saved rules.

        Returns:
            The matching decision, or None if no rule matches.
        """
        for rule in self._rules:
            if rule.matches(tool_name, path):
                return rule.effect
        return None
