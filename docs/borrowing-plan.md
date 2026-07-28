# AgentsX 借鉴计划

**日期**: 2026-07-27  
**基础**: `harness-comparative-analysis.md` 对比分析 + 源码探索  
**目标**: 从 Pi、Tau、Hermes-Agent、OpenCode 中提取最高价值的改进方向

---

## 优先级评估矩阵

| 优先级 | 价值 | 实施难度 | 说明 |
|--------|------|----------|------|
| **P0** | 高 | 低 | 立即实施，ROI 最高 |
| **P1** | 高 | 中 | 核心能力提升 |
| **P2** | 中 | 中 | 有明确收益 |
| **P3** | 中 | 高 | 架构级改动 |

---

## P0 — 立即实施（高价值 × 低难度）

### 1. 上下文压缩：结构化摘要 + 工具输出预剪枝

**来源**: Hermes `agent/context_compressor.py`  
**当前状态**: `agentsx/context/compaction.py` 仅做消息计数/token 阈值截断（196 行），无 LLM 摘要。

**差距**:
- 无结构化摘要模板（目标/进度/决策/下一步）
- 工具输出未预剪枝就送入摘要 LLM（浪费 token）
- 无迭代摘要更新（多次压缩后信息丢失）
- 无 token 预算尾部保护
- 摘要末尾无边界标记

**借鉴方案**:

```
Phase 1 — 工具输出预剪枝（无 LLM 调用）
  - terminal: 保留 命令 + 退出码 + 行数
  - read_file: 保留 路径 + 字符数
  - grep/glob: 保留 模式 + 匹配数
  - 长输出替换为一行摘要

Phase 2 — 结构化摘要模板
  ## 已完成任务
  ## 进行中
  ## 关键决策
  ## 相关文件

Phase 3 — 迭代摘要 + 尾部保护
  - 已有摘要时合并新旧
  - 最近 N 条消息即使超预算也保留
  - 摘要末尾添加边界标记
```

**实施文件**:
- `agentsx/context/compaction.py` — 重写 `compact_messages()` 为 LLM 驱动
- `agentsx/context/tool_pruner.py` — 新建工具输出预剪枝模块
- `agentsx/config.py` — 添加压缩配置项

**工作量**: 2-3 天 | **价值**: 最高（解决长对话上下文丢失）  
**状态**: ✅ 已实施 — `tool_pruner.py` 新建, `compaction.py` 重写, agent loop 已集成

---

### 2. 子代理：工具阻断 + 角色隔离

**来源**: Hermes `tools/delegate_tool.py`  
**当前状态**: `agentsx/agent/subagent.py` 仅限制为只读工具集。

**差距**:
- 无 `DELEGATE_BLOCKED_TOOLS`（子代理可递归委托）
- 无编排者/叶节点角色

**借鉴方案**:

```python
DELEGATE_BLOCKED_TOOLS = frozenset({
    "tool_subagent",  # 禁止递归委托
})

class SubAgentRole(str, Enum):
    LEAF = "leaf"
    ORCHESTRATOR = "orchestrator"
```

**实施文件**:
- `agentsx/agent/subagent.py` — 添加角色、工具阻断
- `agentsx/tools/builtin/orchestration/subagent.py` — 传递角色到子代理

**工作量**: 0.5 天 | **价值**: 安全性提升  
**状态**: ✅ 已实施 — `DELEGATE_BLOCKED_TOOLS`, `SubAgentRole`, 角色过滤 + 深度限制

---

## P1 — 核心能力提升（高价值 × 中难度）

### 3. 工具输出预剪枝模块

**来源**: Hermes `_summarize_tool_result()`  
**当前状态**: 压缩时仅取工具输出前 200 字符。

**借鉴方案**:

```python
def summarize_tool_output(tool_name: str, args: dict, content: str) -> str:
    if tool_name == "tool_bash":
        cmd = args.get("command", "")[:80]
        return f"[terminal] ran `{cmd}` -> {content.count(chr(10))+1} lines"
    if tool_name == "tool_file_read":
        return f"[read] {args.get('path','?')} ({len(content):,} chars)"
    if tool_name == "tool_file_grep":
        return f"[grep] '{args.get('pattern','?')}' ({len(content):,} chars)"
    return f"[{tool_name}] ({len(content):,} chars)"
```

**实施文件**:
- `agentsx/context/tool_pruner.py` — 新建
- `agentsx/context/compaction.py` — 压缩前调用预剪枝

**工作量**: 1 天 | **价值**: 压缩质量显著提升

---

### 4. 扩展 API：从 Observer 升级为 Interceptor

**来源**: Hermes 20+ 生命周期钩子  
**当前状态**: `extensions/api.py` 明确设计为 observer-only（有意为之）。

**差距**: 无 `pre_tool_call` / `post_tool_call` 拦截能力。

**借鉴方案** — 增量扩展，不破坏现有模型:

```python
class InterceptorEvent(ExtensionEvent):
    """可拦截的事件，handler 返回值可修改执行流。"""

    def suppress(self) -> None:
        """阻止后续 handler 和默认行为。"""
        self._suppressed = True

    def modify(self, data: dict[str, Any]) -> None:
        """修改事件数据。"""
        self.data.update(data)
        self._modified = True

EVENT_PRE_TOOL_CALL = "pre_tool_call"
EVENT_POST_TOOL_CALL = "post_tool_call"
EVENT_PRE_COMPACT = "pre_compact"
EVENT_SESSION_START = "session_start"
EVENT_SESSION_END = "session_end"
```

**实施文件**:
- `agentsx/extensions/api.py` — 新增 `InterceptorEvent` + 事件常量
- `agentsx/agent/loop.py` — 在工具调用前后 emit 拦截事件
- `agentsx/context/compaction.py` — 压缩前 emit 事件

**工作量**: 1.5 天 | **价值**: 插件能力扩展  
**状态**: ✅ 已实施 — `InterceptorEvent` + `emit_interceptor()` + 5 个新事件常量, agent loop 已集成 pre/post tool call 拦截

---

### 5. 多源插件发现

**来源**: Hermes `hermes_cli/plugins.py` 的 4 源发现  
**当前状态**: 仅 `entry_points(group="agentsx.extensions")` 单源。

**借鉴方案**:

```python
def discover_extensions() -> dict[str, Any]:
    sources = [
        ("entry_points", _discover_entry_points),    # pip
        ("user", _discover_user_plugins),             # ~/.agentsx/extensions/
        ("project", _discover_project_plugins),       # .agentsx/extensions/
        ("builtin", _discover_builtin_plugins),       # 内置
    ]
    extensions = {}
    for source_name, discovery_fn in sources:
        try:
            found = discovery_fn()
            extensions.update(found)
        except Exception as e:
            logger.warning("Plugin discovery from %s failed: %s", source_name, e)
    return extensions
```

**实施文件**:
- `agentsx/extensions/discovery.py` — 新建多源发现模块
- `agentsx/extensions/api.py` — 使用新的发现机制

**工作量**: 1 天 | **价值**: 用户可本地开发插件  
**状态**: ✅ 已实施 — `agentsx/extensions/discovery.py` (4 源发现: entry_points, user, project, builtin) + `ExtensionAPI.load_extensions()`

---

## P2 — 有明确收益（中价值 × 中难度）

### 6. 权限系统：通配符规则 + "始终允许"持久化

**来源**: OpenCode `permission.ts`  
**当前状态**: `security/policy.py` 使用 fnmatch，无持久化。

**借鉴方案**:

```python
@dataclass
class WildcardRule:
    action: str    # e.g. "tool_file_read", "*"
    resource: str  # e.g. "/path/*", "*"
    effect: Decision

def evaluate_wildcard(action: str, resource: str, rules: list[WildcardRule]) -> Decision:
    for rule in rules:
        if fnmatch(action, rule.action) and fnmatch(resource, rule.resource):
            return rule.effect
    return Decision.PROMPT

class SavedRules:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._rules: list[WildcardRule] = self._load()

    def add(self, action: str, resource: str) -> None:
        self._rules.append(WildcardRule(action, resource, Decision.ALLOW))
        self._save()

    def list(self) -> list[WildcardRule]:
        return list(self._rules)
```

**实施文件**:
- `agentsx/security/policy.py` — 增强规则匹配
- `agentsx/security/saved_rules.py` — 新建持久化模块

**工作量**: 1.5 天 | **价值**: 减少重复审批  
**状态**: ✅ 已实施 — `SavedRulesStore` + `SavedRule` + `ExecutionPolicy` 集成, 17 个新测试

---

### 7. 会话：压缩前快照 + 回滚

**来源**: OpenCode `session.ts` 的 `revert` + `Snapshot`  
**当前状态**: 有 JSONL + SQLite 双后端，但无文件系统快照。

**借鉴方案**:

```python
class SessionSnapshot:
    def __init__(self, session_id: str, base_dir: Path) -> None:
        self._session_id = session_id
        self._base_dir = base_dir
        self._snapshot_dir = base_dir / ".snapshots" / session_id

    def capture_file_state(self, paths: list[Path]) -> dict[str, bytes]:
        state = {}
        for p in paths:
            if p.exists():
                state[str(p)] = p.read_bytes()
        return state

    def rollback(self, state: dict[str, bytes]) -> None:
        for path_str, content in state.items():
            Path(path_str).write_bytes(content)
```

**实施文件**:
- `agentsx/session/snapshot.py` — 新建
- `agentsx/context/compaction.py` — 压缩前创建快照

**工作量**: 1 天 | **价值**: 压缩安全性提升  
**状态**: ✅ 已实施 — `SessionSnapshot` + `FileSnapshot`, 10 个新测试

---

## P3 — 架构级改动（中价值 × 高难度）

### 8. 效果系统借鉴（非引入 Effect 库）

**来源**: OpenCode 的 Effect 模式  
**评估**: TypeScript 专用，不引入库，仅借鉴思想：

```python
class CompactionError(Exception):
    def __init__(self, reason: str, retryable: bool = True) -> None:
        self.reason = reason
        self.retryable = retryable

@dataclass
class Result[T, E]:
    value: T | None = None
    error: E | None = None

    @classmethod
    def ok(cls, value: T) -> "Result[T, E]":
        return cls(value=value)

    @classmethod
    def err(cls, error: E) -> "Result[T, E]":
        return cls(error=error)
```

**工作量**: 2 天 | **价值**: 错误处理更清晰

---

### 9. 记忆系统（独立项目）

**来源**: Hermes `memory_manager.py`  
**评估**: 大型功能，建议作为独立项目，不在此计划实施。

---

## 不建议借鉴的方面

| 方面 | 原因 |
|------|------|
| Pi bubblewrap 沙箱 | 仅 Linux，跨平台差 |
| Tau goroutine/channel | Python 无 goroutine |
| Hermes 完整插件系统 | 过于庞大，与 observer-only 设计冲突 |
| OpenCode Effect 库 | TypeScript 专用 |
| Hermes 记忆系统 | 独立项目级别 |

---

## 实施路线图

```
Week 1:
  Day 1-2: P0 #1 — 结构化压缩
  Day 3:   P0 #2 — 子代理工具阻断
  Day 4:   P1 #3 — 工具输出预剪枝
  Day 5:   P1 #4 — 扩展拦截器

Week 2:
  Day 1:   P1 #5 — 多源插件发现
  Day 2-3: P2 #6 — 权限持久化
  Day 4:   P2 #7 — 会话快照
  Day 5:   P3 #8 — 效果系统评估
```

---

## 总结

| 优先级 | 项目 | 核心价值 | 工作量 | 状态 |
|--------|------|----------|--------|------|
| **P0** | 结构化压缩 | 解决长对话上下文丢失 | 2-3 天 | ✅ 已完成 |
| **P0** | 子代理工具阻断 | 防止递归爆炸 | 0.5 天 | ✅ 已完成 |
| **P1** | 工具输出预剪枝 | 提升压缩质量 | 1 天 | 待实施 |
| **P1** | 扩展拦截器 | 插件能力扩展 | 1.5 天 | ✅ 已完成 |
| **P1** | 多源插件发现 | 用户本地开发 | 1 天 | ✅ 已完成 |
| **P2** | 权限持久化 | 减少重复审批 | 1.5 天 | ✅ 已完成 |
| **P2** | 会话快照 | 压缩安全性 | 1 天 | ✅ 已完成 |
| **P3** | 效果系统借鉴 | 错误处理清晰化 | 2 天 | 待实施 |

**最高 ROI**: P0 #1（结构化压缩）— 直接解决最普遍的用户痛点，实施难度可控。  
**已完成**: P0 两项核心优化已全部实施并通过验证 (271 tests passed, lint clean, type check clean)。
