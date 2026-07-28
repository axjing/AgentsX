"""Tests for saved rules persistence (``agentsx/security/saved_rules.py``)."""

import json
import tempfile
from pathlib import Path

import pytest

from agentsx.protocol.messages import Decision
from agentsx.security.saved_rules import SavedRule, SavedRulesStore


class TestSavedRule:
    """SavedRule dataclass."""

    def test_creation(self) -> None:
        rule = SavedRule(
            action="tool_file_write",
            resource="/tmp/*",
            effect=Decision.ALLOW,
            note="build dir",
        )
        assert rule.action == "tool_file_write"
        assert rule.resource == "/tmp/*"
        assert rule.effect == Decision.ALLOW
        assert rule.note == "build dir"

    def test_matches(self) -> None:
        rule = SavedRule("tool_file_write", "/tmp/*", Decision.ALLOW)
        assert rule.matches("tool_file_write", "/tmp/test.py")
        assert not rule.matches("tool_file_read", "/tmp/test.py")
        assert not rule.matches("tool_file_write", "/home/user/test.py")

    def test_matches_wildcard_action(self) -> None:
        rule = SavedRule("*", "*", Decision.ALLOW)
        assert rule.matches("tool_bash", "anything")
        assert rule.matches("tool_file_write", "/any/path")

    def test_roundtrip(self) -> None:
        rule = SavedRule("tool_bash", "*", Decision.FORBIDDEN, note="no bash")
        d = rule.to_dict()
        restored = SavedRule.from_dict(d)
        assert restored.action == rule.action
        assert restored.resource == rule.resource
        assert restored.effect == rule.effect
        assert restored.note == rule.note


class TestSavedRulesStore:
    """SavedRulesStore — add, remove, evaluate, persistence."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SavedRulesStore:
        rules_file = tmp_path / "rules.json"
        return SavedRulesStore(path=rules_file)

    def test_empty_store(self, store: SavedRulesStore) -> None:
        assert store.list() == []
        assert store.evaluate("tool_bash", "/tmp/x") is None

    def test_add_and_list(self, store: SavedRulesStore) -> None:
        store.add("tool_file_write", "/tmp/*", Decision.ALLOW)
        store.add("tool_bash", "*", Decision.FORBIDDEN)
        rules = store.list()
        assert len(rules) == 2
        assert rules[0].action == "tool_file_write"
        assert rules[1].effect == Decision.FORBIDDEN

    def test_evaluate_match(self, store: SavedRulesStore) -> None:
        store.add("tool_file_write", "/tmp/*", Decision.ALLOW)
        assert store.evaluate("tool_file_write", "/tmp/test.py") == Decision.ALLOW
        assert store.evaluate("tool_bash", "ls") is None

    def test_remove(self, store: SavedRulesStore) -> None:
        store.add("tool_file_write", "/tmp/*", Decision.ALLOW)
        assert store.remove(0) is True
        assert store.list() == []

    def test_remove_out_of_range(self, store: SavedRulesStore) -> None:
        assert store.remove(99) is False

    def test_clear(self, store: SavedRulesStore) -> None:
        store.add("tool_file_write", "/tmp/*", Decision.ALLOW)
        store.add("tool_bash", "*", Decision.FORBIDDEN)
        store.clear()
        assert store.list() == []

    def test_persistence(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.json"
        # Write
        store1 = SavedRulesStore(path=rules_file)
        store1.add("tool_file_write", "/tmp/*", Decision.ALLOW)
        # Read
        store2 = SavedRulesStore(path=rules_file)
        assert len(store2.list()) == 1
        assert store2.list()[0].action == "tool_file_write"

    def test_persistence_corrupt_file(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.json"
        rules_file.write_text("not json!!!")
        store = SavedRulesStore(path=rules_file)
        assert store.list() == []

    def test_persistence_missing_file(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "nonexistent.json"
        store = SavedRulesStore(path=rules_file)
        assert store.list() == []


class TestExecutionPolicyWithSavedRules:
    """ExecutionPolicy integration with SavedRulesStore."""

    def test_saved_allow_overrides_default(self, tmp_path: Path) -> None:
        from agentsx.security.policy import ExecutionPolicy

        store = SavedRulesStore(path=tmp_path / "rules.json")
        store.add("tool_file_write", "/tmp/*", Decision.ALLOW)

        policy = ExecutionPolicy(saved_rules_store=store)
        # Default would be PROMPT, but saved rule says ALLOW
        assert policy.evaluate(
            "tool_file_write",
            {"path": "/tmp/test.py"},
        ) == Decision.ALLOW

    def test_saved_forbid_overrides_built_in(self, tmp_path: Path) -> None:
        from agentsx.security.policy import ExecutionPolicy, Rule

        store = SavedRulesStore(path=tmp_path / "rules.json")
        store.add("tool_file_read", "*", Decision.FORBIDDEN)

        policy = ExecutionPolicy(
            rules=[Rule("tool_file_read:*", Decision.ALLOW)],
            saved_rules_store=store,
        )
        # Built-in says ALLOW, but saved rule says FORBIDDEN
        assert policy.evaluate(
            "tool_file_read",
            {"path": "/any/file.txt"},
        ) == Decision.FORBIDDEN

    def test_no_saved_rules_falls_through(self, tmp_path: Path) -> None:
        from agentsx.security.policy import ExecutionPolicy

        store = SavedRulesStore(path=tmp_path / "rules.json")
        policy = ExecutionPolicy(saved_rules_store=store)
        assert policy.evaluate("tool_bash", {"command": "ls"}) == Decision.PROMPT

    def test_saved_store_none_backward_compat(self) -> None:
        from agentsx.security.policy import ExecutionPolicy

        policy = ExecutionPolicy()
        assert policy.evaluate("tool_bash", {"command": "ls"}) == Decision.PROMPT
