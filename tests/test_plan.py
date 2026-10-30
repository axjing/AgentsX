"""Tests for task planning: TaskPlan and tool_plan tool."""

import pytest

from agentsx.context.plan import TaskPlan, TaskStatus, get_active_plan
from agentsx.tools.builtin.orchestration.planner import tool_plan


class TestTaskPlan:
    """Tests for TaskPlan dataclass."""

    def test_empty_plan(self) -> None:
        plan = TaskPlan()
        assert plan.total_count == 0
        assert plan.completed_count == 0
        assert "No active task plan" in plan.render_markdown()

    def test_set_tasks(self) -> None:
        plan = TaskPlan()
        plan.set_tasks(["Step 1", "Step 2", "Step 3"])
        assert plan.total_count == 3
        assert plan.completed_count == 0
        assert len(plan.tasks) == 3
        assert plan.tasks[0].id == 1
        assert plan.tasks[0].title == "Step 1"
        assert plan.tasks[0].status == TaskStatus.PENDING

    def test_add_task(self) -> None:
        plan = TaskPlan()
        t1 = plan.add_task("Initial task")
        assert t1.id == 1
        t2 = plan.add_task("Follow-up task")
        assert t2.id == 2
        assert plan.total_count == 2

    def test_update_task_status(self) -> None:
        plan = TaskPlan()
        plan.set_tasks(["Task A", "Task B"])
        updated = plan.update_task(1, TaskStatus.IN_PROGRESS)
        assert updated is not None
        assert updated.status == TaskStatus.IN_PROGRESS

        updated2 = plan.update_task(2, "completed")
        assert updated2 is not None
        assert updated2.status == TaskStatus.COMPLETED
        assert plan.completed_count == 1

        # Nonexistent task ID returns None
        assert plan.update_task(99, TaskStatus.COMPLETED) is None

    def test_render_markdown(self) -> None:
        plan = TaskPlan()
        plan.set_tasks(["Design", "Build", "Test"])
        plan.update_task(1, TaskStatus.COMPLETED)
        plan.update_task(2, TaskStatus.IN_PROGRESS)
        md = plan.render_markdown()
        assert "1/3 completed" in md
        assert "[x] 1. Design" in md
        assert "[/] 2. Build" in md
        assert "[ ] 3. Test" in md

    def test_clear_plan(self) -> None:
        plan = TaskPlan()
        plan.set_tasks(["Task 1"])
        plan.clear()
        assert plan.total_count == 0
        assert plan.render_markdown() == "No active task plan."


class TestToolPlan:
    """Tests for tool_plan tool interface."""

    def setup_method(self) -> None:
        get_active_plan().clear()

    def test_view_empty_plan(self) -> None:
        result = tool_plan.fn(action="view")
        assert "No active task plan" in result

    def test_set_tasks_newline_separated(self) -> None:
        result = tool_plan.fn(action="set", tasks="Task 1\nTask 2\nTask 3")
        assert "Plan initialized" in result
        assert "0/3 completed" in result
        assert "[ ] 1. Task 1" in result

    def test_set_tasks_json_array(self) -> None:
        result = tool_plan.fn(action="set", tasks='["First", "Second"]')
        assert "Plan initialized" in result
        assert "0/2 completed" in result
        assert "[ ] 1. First" in result

    def test_set_tasks_empty(self) -> None:
        result = tool_plan.fn(action="set", tasks="")
        assert "Error: no task titles provided" in result

    def test_add_task(self) -> None:
        tool_plan.fn(action="set", tasks="Existing")
        res = tool_plan.fn(action="add", title="Appended task")
        assert "Added task 2: Appended task" in res

    def test_update_task_status(self) -> None:
        tool_plan.fn(action="set", tasks="Step A\nStep B")
        res = tool_plan.fn(action="update", task_id=1, status="in_progress")
        assert "Updated task 1 to 'in_progress'" in res
        assert "[/] 1. Step A" in res

    def test_update_invalid_status(self) -> None:
        tool_plan.fn(action="set", tasks="Step A")
        res = tool_plan.fn(action="update", task_id=1, status="invalid_status")
        assert "Error: invalid status" in res

    def test_update_nonexistent_id(self) -> None:
        tool_plan.fn(action="set", tasks="Step A")
        res = tool_plan.fn(action="update", task_id=99, status="completed")
        assert "Error: task 99 not found" in res

    def test_clear_action(self) -> None:
        tool_plan.fn(action="set", tasks="Step A")
        res = tool_plan.fn(action="clear")
        assert "Task plan cleared" in res
        view_res = tool_plan.fn(action="view")
        assert "No active task plan" in view_res

    def test_unknown_action(self) -> None:
        res = tool_plan.fn(action="unknown_cmd")
        assert "Unknown action 'unknown_cmd'" in res

    @pytest.mark.asyncio
    async def test_async_call_wrapper(self) -> None:
        res = await tool_plan.call(action="set", tasks="Async task")
        assert "Plan initialized" in res.content
