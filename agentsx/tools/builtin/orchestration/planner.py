"""Task planning tool for multi-step goals."""

import json

from agentsx.context.plan import TaskStatus, get_active_plan
from agentsx.tools import TOOLSET_ORCHESTRATION, tool


@tool(
    description="Manage and track multi-step task execution plan.",
    toolset=TOOLSET_ORCHESTRATION,
)
def tool_plan(
    action: str = "view",
    tasks: str = "",
    task_id: int = 0,
    status: str = "",
    title: str = "",
) -> str:
    """Manage and inspect the multi-step task plan.

    Args:
        action: One of ``"view"``, ``"set"``, ``"add"``, ``"update"``, ``"clear"``.
        tasks: Newline-separated task titles or JSON array for action="set".
        task_id: 1-based task ID for action="update".
        status: Target status for update: "pending", "in_progress", "completed".
        title: Single task title for action="add".

    Returns:
        Rendered task plan or operation status.
    """
    plan = get_active_plan()
    act = action.strip().lower()

    if act == "view":
        return plan.render_markdown()

    if act == "set":
        task_list: list[str] = []
        clean_tasks = tasks.strip()
        if clean_tasks.startswith("[") and clean_tasks.endswith("]"):
            try:
                parsed = json.loads(clean_tasks)
                if isinstance(parsed, list):
                    task_list = [str(x) for x in parsed]
            except json.JSONDecodeError:
                task_list = clean_tasks.splitlines()
        else:
            task_list = clean_tasks.splitlines()

        if not task_list:
            return "Error: no task titles provided to set."
        plan.set_tasks(task_list)
        return f"Plan initialized:\n\n{plan.render_markdown()}"

    if act == "add":
        clean_title = (title or tasks).strip()
        if not clean_title:
            return "Error: task title is required to add."
        item = plan.add_task(clean_title)
        return f"Added task {item.id}: {item.title}\n\n{plan.render_markdown()}"

    if act == "update":
        if task_id <= 0:
            return "Error: valid positive task_id is required to update."
        clean_status = status.strip().lower()
        try:
            target_status = TaskStatus(clean_status)
        except ValueError:
            valid_statuses = ", ".join(s.value for s in TaskStatus)
            return f"Error: invalid status '{status}'. Valid options: {valid_statuses}"

        updated = plan.update_task(task_id, target_status)
        if not updated:
            return f"Error: task {task_id} not found in active plan."
        status_val = updated.status.value
        return f"Updated task {task_id} to '{status_val}'.\n\n{plan.render_markdown()}"

    if act == "clear":
        plan.clear()
        return "Task plan cleared."

    return (
        f"Unknown action '{action}'. "
        "Supported actions: 'view', 'set', 'add', 'update', 'clear'."
    )
