"""Tests for RSI verification contract and branch revert slash commands."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agentsx.cli.commands import cmd_help, cmd_revert, cmd_verify
from agentsx.cli.repl import handle_command
from agentsx.protocol.messages import AgentMessage, MessageRole
from agentsx.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def sqlite_store(tmp_path: Path) -> SQLiteSessionStore:
    """Provide a temporary SQLiteSessionStore."""
    db_file = tmp_path / "sessions.db"
    return SQLiteSessionStore(db_path=db_file)


# ── cmd_verify Tests ──────────────────────────────────────────────────


def test_cmd_verify_no_suite(tmp_path: Path) -> None:
    """Test verify command when no known test runner file exists."""
    output = cmd_verify(project_dir=tmp_path)
    assert "No known test suite detected" in output


def test_cmd_verify_pytest_passed(tmp_path: Path) -> None:
    """Test verify command detects pyproject.toml and reports PASSED."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

    fake_proc = subprocess.CompletedProcess(
        args=["pytest"],
        returncode=0,
        stdout="5 passed in 0.20s",
        stderr="",
    )
    with patch("subprocess.run", return_value=fake_proc) as mock_run:
        output = cmd_verify(project_dir=tmp_path)
        assert "[pytest verification: PASSED]" in output
        assert "5 passed in 0.20s" in output
        mock_run.assert_called_once()


def test_cmd_verify_pytest_failed(tmp_path: Path) -> None:
    """Test verify command reports FAILED with exit code."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")

    fake_proc = subprocess.CompletedProcess(
        args=["pytest"],
        returncode=1,
        stdout="FAILED test_foo.py::test_bar - AssertionError",
        stderr="",
    )
    with patch("subprocess.run", return_value=fake_proc):
        output = cmd_verify(project_dir=tmp_path)
        assert "[pytest verification: FAILED (exit 1)]" in output
        assert "AssertionError" in output


def test_cmd_verify_npm_test(tmp_path: Path) -> None:
    """Test verify command detects package.json."""
    (tmp_path / "package.json").write_text('{"name": "demo"}')

    fake_proc = subprocess.CompletedProcess(
        args=["npm", "test"],
        returncode=0,
        stdout="PASS src/index.test.js",
        stderr="",
    )
    with patch("subprocess.run", return_value=fake_proc):
        output = cmd_verify(project_dir=tmp_path)
        assert "[npm test verification: PASSED]" in output


def test_cmd_verify_cargo_test(tmp_path: Path) -> None:
    """Test verify command detects Cargo.toml."""
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "demo"\n')

    fake_proc = subprocess.CompletedProcess(
        args=["cargo", "test"],
        returncode=0,
        stdout="test result: ok. 2 passed",
        stderr="",
    )
    with patch("subprocess.run", return_value=fake_proc):
        output = cmd_verify(project_dir=tmp_path)
        assert "[cargo test verification: PASSED]" in output


def test_cmd_verify_go_test(tmp_path: Path) -> None:
    """Test verify command detects go.mod."""
    (tmp_path / "go.mod").write_text("module demo\n")

    fake_proc = subprocess.CompletedProcess(
        args=["go", "test", "./..."],
        returncode=0,
        stdout="ok  \tdemo\t0.005s",
        stderr="",
    )
    with patch("subprocess.run", return_value=fake_proc):
        output = cmd_verify(project_dir=tmp_path)
        assert "[go test verification: PASSED]" in output


def test_cmd_verify_timeout(tmp_path: Path) -> None:
    """Test verify command handles execution timeout."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=60),
    ):
        output = cmd_verify(project_dir=tmp_path)
        assert "TIMEOUT after 60s" in output


def test_cmd_verify_os_error(tmp_path: Path) -> None:
    """Test verify command handles OS/Subprocess errors gracefully."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

    with patch("subprocess.run", side_effect=OSError("Exec failure")):
        output = cmd_verify(project_dir=tmp_path)
        assert "verification error: Exec failure" in output


# ── cmd_revert Tests ──────────────────────────────────────────────────


def test_cmd_revert_empty_messages(sqlite_store: SQLiteSessionStore) -> None:
    """Test revert with no messages in conversation."""
    sess = sqlite_store.create("gpt-4o", "Test")
    msg, new_id = cmd_revert(sqlite_store, sess.id, [])
    assert "No messages to revert" in msg
    assert new_id is None


def test_cmd_revert_no_user_turn(sqlite_store: SQLiteSessionStore) -> None:
    """Test revert when conversation has no user messages."""
    sess = sqlite_store.create("gpt-4o", "Test")
    messages = [AgentMessage(role=MessageRole.SYSTEM, content="System prompt")]
    msg, new_id = cmd_revert(sqlite_store, sess.id, messages)
    assert "No user turn found to revert" in msg
    assert new_id is None


def test_cmd_revert_single_turn(sqlite_store: SQLiteSessionStore) -> None:
    """Test revert rolls back the latest turn and branches cleanly."""
    sess = sqlite_store.create("gpt-4o", "Main Task")
    m0 = AgentMessage(role=MessageRole.SYSTEM, content="System prompt")
    m1 = AgentMessage(role=MessageRole.USER, content="Bad prompt")
    m2 = AgentMessage(role=MessageRole.ASSISTANT, content="Failed plan")
    for m in (m0, m1, m2):
        sqlite_store.append(sess.id, m)

    messages = [m0, m1, m2]
    msg, new_id = cmd_revert(
        sqlite_store,
        sess.id,
        messages,
        reason="infinite tool loop",
    )

    assert "Reverted to turn before message #1" in msg
    assert "reason: infinite tool loop" in msg
    assert new_id is not None
    assert new_id != sess.id

    # In-memory history trimmed to before the failed user turn
    assert len(messages) == 1
    assert messages[0].content == "System prompt"

    # Branch session verified in store
    branched_sess = sqlite_store.get(new_id)
    assert "Revert: infinite tool loop" in branched_sess.title
    branched_msgs = sqlite_store.get_messages(new_id)
    assert len(branched_msgs) == 1
    assert branched_msgs[0].content == "System prompt"


def test_cmd_revert_multi_turn(sqlite_store: SQLiteSessionStore) -> None:
    """Test revert preserves earlier successful turns."""
    sess = sqlite_store.create("gpt-4o", "Multi Turn")
    m0 = AgentMessage(role=MessageRole.SYSTEM, content="Sys")
    m1 = AgentMessage(role=MessageRole.USER, content="Step 1: OK")
    m2 = AgentMessage(role=MessageRole.ASSISTANT, content="Done 1")
    m3 = AgentMessage(role=MessageRole.USER, content="Step 2: Bad")
    m4 = AgentMessage(role=MessageRole.ASSISTANT, content="Fail 2")
    for m in (m0, m1, m2, m3, m4):
        sqlite_store.append(sess.id, m)

    messages = [m0, m1, m2, m3, m4]
    msg, new_id = cmd_revert(sqlite_store, sess.id, messages)

    assert "Reverted to turn before message #3" in msg
    assert new_id is not None
    assert len(messages) == 3
    assert messages[1].content == "Step 1: OK"
    assert messages[2].content == "Done 1"

    branched_msgs = sqlite_store.get_messages(new_id)
    assert len(branched_msgs) == 3


# ── REPL Dispatch & Help Tests ────────────────────────────────────────


def test_repl_verify_command() -> None:
    """Test /verify slash command handled in REPL."""
    with patch("agentsx.cli.commands.cmd_verify", return_value="[PASSED]") as mock_v:
        new_id, model = handle_command("/verify", [])
        mock_v.assert_called_once()
        assert new_id is None
        assert model == "unknown"


def test_repl_revert_command(sqlite_store: SQLiteSessionStore) -> None:
    """Test /revert slash command dispatched through handle_command."""
    sess = sqlite_store.create("gpt-4o", "Chat")
    m0 = AgentMessage(role=MessageRole.SYSTEM, content="Sys")
    m1 = AgentMessage(role=MessageRole.USER, content="Bad turn")
    messages = [m0, m1]

    new_id, _ = handle_command(
        "/revert syntax error",
        messages,
        store=sqlite_store,
        session_id=sess.id,
    )
    assert new_id is not None
    assert len(messages) == 1


def test_repl_rollback_alias(sqlite_store: SQLiteSessionStore) -> None:
    """Test /rollback alias performs the same revert operation."""
    sess = sqlite_store.create("gpt-4o", "Chat")
    m0 = AgentMessage(role=MessageRole.SYSTEM, content="Sys")
    m1 = AgentMessage(role=MessageRole.USER, content="Bad turn")
    messages = [m0, m1]

    new_id, _ = handle_command(
        "/rollback",
        messages,
        store=sqlite_store,
        session_id=sess.id,
    )
    assert new_id is not None
    assert len(messages) == 1


def test_cmd_help_includes_rsi_commands() -> None:
    """Test help string includes /verify, /revert, /memory, /plan, /model, /status."""
    help_text = cmd_help()
    assert "/verify" in help_text
    assert "/revert" in help_text
    assert "/memory" in help_text
    assert "/plan" in help_text
    assert "/model" in help_text
    assert "/status" in help_text


def test_repl_memory_command() -> None:
    """Test /memory slash command handled in REPL."""
    with patch("agentsx.cli.commands.cmd_memory", return_value="Memory") as mock_m:
        new_id, model = handle_command("/memory show", [])
        mock_m.assert_called_once_with(action="show")
        assert new_id is None
        assert model == "unknown"


def test_repl_plan_command() -> None:
    """Test /plan slash command handled in REPL."""
    with patch("agentsx.cli.commands.cmd_plan", return_value="Plan") as mock_p:
        new_id, model = handle_command("/plan view", [])
        mock_p.assert_called_once_with(action="view")
        assert new_id is None
        assert model == "unknown"


def test_repl_model_command() -> None:
    """Test /model slash command handled in REPL."""
    with patch(
        "agentsx.cli.commands.cmd_model",
        return_value=("Switched", "claude-3-5-sonnet"),
    ) as mock_m:
        new_id, model = handle_command(
            "/model claude-3-5-sonnet",
            [],
            model_name="gpt-4o",
        )
        mock_m.assert_called_once_with("gpt-4o", "claude-3-5-sonnet")
        assert new_id is None
        assert model == "claude-3-5-sonnet"


def test_repl_status_command() -> None:
    """Test /status slash command handled in REPL."""
    with patch(
        "agentsx.cli.commands.cmd_status",
        return_value="Status info",
    ) as mock_s:
        new_id, model = handle_command(
            "/status",
            [],
            session_id="s123",
            model_name="gpt-4o",
        )
        mock_s.assert_called_once_with(
            session_id="s123",
            model_name="gpt-4o",
            messages=[],
        )
        assert new_id is None
        assert model == "gpt-4o"
