"""Workspace awareness for the agent runtime.

Provides workspace lifecycle management, git status tracking,
and file tree indexing.
"""

from __future__ import annotations

from agentsx.workspace.file_tree import FileTreeIndex, FileTreeNode
from agentsx.workspace.git import GitStatus, GitWatcher
from agentsx.workspace.manager import WorkspaceInfo, WorkspaceManager

__all__ = [
    "FileTreeIndex",
    "FileTreeNode",
    "GitStatus",
    "GitWatcher",
    "WorkspaceInfo",
    "WorkspaceManager",
]
