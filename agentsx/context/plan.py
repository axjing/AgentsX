"""Task planning and progress tracking.

Provides lightweight task list and progress tracking for multi-step goals.
Inspired by Claude Code scratchpad and OpenHands todo tracker.
"""

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    """Status of a planned task item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class TaskItem:
    """A single item in a task plan."""

    id: int
    title: str
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class TaskPlan:
    """In-memory multi-step task plan with status tracking."""

    tasks: list[TaskItem] = field(default_factory=list)
    _next_id: int = 1

    def set_tasks(self, titles: list[str]) -> list[TaskItem]:
        """Replace current tasks with a new list of pending tasks."""
        self.tasks.clear()
        self._next_id = 1
        for title in titles:
            clean = title.strip()
            if clean:
                self.tasks.append(
                    TaskItem(id=self._next_id, title=clean, status=TaskStatus.PENDING)
                )
                self._next_id += 1
        return self.tasks

    def add_task(self, title: str) -> TaskItem:
        """Add a single task to the end of the plan."""
        item = TaskItem(
            id=self._next_id,
            title=title.strip(),
            status=TaskStatus.PENDING,
        )
        self.tasks.append(item)
        self._next_id += 1
        return item

    def update_task(self, task_id: int, status: TaskStatus | str) -> TaskItem | None:
        """Update the status of a specific task by its 1-based ID."""
        target_status = TaskStatus(status) if isinstance(status, str) else status
        for item in self.tasks:
            if item.id == task_id:
                item.status = target_status
                return item
        return None

    def clear(self) -> None:
        """Clear all tasks from the plan."""
        self.tasks.clear()
        self._next_id = 1

    @property
    def completed_count(self) -> int:
        """Return the number of completed tasks."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)

    @property
    def total_count(self) -> int:
        """Return the total number of tasks."""
        return len(self.tasks)

    def render_markdown(self) -> str:
        """Format the task plan into a human-readable Markdown checklist."""
        if not self.tasks:
            return "No active task plan."

        lines = [
            f"### Task Plan ({self.completed_count}/{self.total_count} completed)\n"
        ]
        status_markers = {
            TaskStatus.PENDING: "[ ]",
            TaskStatus.IN_PROGRESS: "[/]",
            TaskStatus.COMPLETED: "[x]",
            TaskStatus.CANCELLED: "[-]",
        }
        for item in self.tasks:
            marker = status_markers.get(item.status, "[ ]")
            lines.append(f"{marker} {item.id}. {item.title}")

        return "\n".join(lines)


# Singleton instance for active runtime session
_active_plan = TaskPlan()


def get_active_plan() -> TaskPlan:
    """Return the global active task plan singleton."""
    return _active_plan
