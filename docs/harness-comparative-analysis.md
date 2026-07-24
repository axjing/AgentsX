# AgentsX Harness Design — 多项目对比分析报告

**日期**: 2026-07-24  
**范围**: Pi、Tau、Hermes-Agent、OpenCode 与 AgentsX 五个项目的 Harness 工程设计对比

---

## 1. 执行摘要

| 维度 | Pi (TypeScript) | Tau (Python) | Hermes-Agent (Python) | OpenCode (TypeScript) | AgentsX (Python) |
|------|---------|----------|----------------------|------------------|-----------------|
| **Agent Loop** | 有限状态机 (FSM) | 事件驱动 | 事件驱动 | Effect 函数式系统 | 纯 async 生成器 (ReAct) |
| **消息模型** | 强类型 Message struct | JSONL append-only | AgentMessage dataclass | Protocol Message 接口 | AgentMessage dataclass |
| **上下文管理** | 分支摘要 (Branch-summarize) | Token 预算自动压缩 | ContextCompressor | 上下文窗口管理 | CJK-aware 智能压缩 |
| **工具系统** | TypeScript struct + 沙箱执行 | ToolRegistry + JSON Schema | ToolSpec + 插件系统 | 配置化 + Effect 分发 | @tool() 装饰器 + 风险分级 |
| **Provider 层** | 多 Provider 接口 | Factory + retry | 多 LLM 适配器 | 配置驱动 | Transport/Provider 双层架构 |
| **会话持久化** | 文件树会话 | JSONL append-only | 内存 + 可选持久化 | SQLite | JSONL + SQLite 双后端 |
| **安全模型** | 沙箱 (bubblewrap) | Policy 引擎 | ExecutionPolicy | 权限分级 | 4 层安全栈 (Policy+PathGuard+CommandGuard+Limit) |
| **错误恢复** | Retry + fallback | Retry + 自动压缩 | Retry with backoff | 重试循环 | 分类错误 + 智能恢复 |
| **扩展性** | 技能系统 | 事件系统 | 插件系统 | 插件架构 | Observer API + entry_points |

---

## 2. Agent Loop 架构深度对比

### 2.1 Pi — 有限状态机 (FSM)

```
UserInput → ContextLoad → LLMRequest → ToolExecute → ContextUpdate → Loop/Exit
               ↓                                                      ↓
         (branch check)                                       (summarize if needed)
```

**关键设计**：
- TypeScript 语言实现，显式状态转换，每个状态有 entry/exit 函数
- `State` 类型定义所有可能状态，转换路径确定
- 上下文压缩在分支切换时触发 (branch-summarize)
- 分支管理内建于循环中
- 沙箱执行通过 bubblewrap 实现 Linux 级隔离 

**优势**：可预测、易调试、状态转换可追溯  
**劣势**：中途打断不够灵活，分支摘要粒度较粗

### 2.2 Tau — 事件驱动架构

```
UserInput → Context → LLM Stream (goroutine) → Tool Queue → Execute → Observe → Repeat
                         ↓                              ↓
                   channels + select            channel-based results
```

**关键设计**：
- Python 事件驱动并发流式 LLM 响应，事件传递工具执行结果
- 上下文压缩由 token 预算阈值触发，循环内自动执行
- 工具执行队列化，支持并行执行
- 3 层架构：`tau_ai` (Provider) → `tau_agent` (Agent Brain) → `tau_coding` (Application)
- 依赖方向严格单向：`tau_coding → tau_agent → tau_ai`

**优势**：并发非阻塞、天然流式、工具执行可并行  
**劣势**：channel 复杂性高，执行顺序难推理

### 2.3 Hermes-Agent — 事件驱动架构

```
Event Bus → Agent Loop → LLM → Tool Call → Event Emit → Loop Continue
    ↓
  (on_tool_start, on_tool_result, on_error, ...)
```

**关键设计**：
- 中心 `ContextManager` 协调循环，事件总线解耦各组件
- 每步发射事件 (tool start, result, error)，扩展点通过事件订阅
- 工具执行通过事件总线解耦，`ToolSpec` 定义 + 插件系统发现
- `ContextCompressor` 支持可选 LLM 语义摘要

**优势**：解耦、可观测、扩展点丰富  
**劣势**：事件总线开销，执行流追踪困难

### 2.4 OpenCode — 函数式 Effect 系统

```
Intent → Effect Dispatch → LLM → Tool Effect → Result → Continue
           ↓                        ↓
      (pure function)        (side-effect isolation)
```

**关键设计**：
- TypeScript 实现，Effect 作为纯函数包装副作用
- 工具执行作为 Effect dispatch，副作用隔离
- Provider 通过配置驱动 (opencode.jsonc)
- 丰富的 TUI 基于 Effect 结果渲染

**优势**：纯函数可测试、副作用隔离、组合性强  
**劣势**：TypeScript 复杂性陡，学习曲线高

### 2.5 AgentsX — 纯 Async 生成器 (ReAct Pattern)

```
run_agent_loop() → yield ModelRequestEvent
                   yield TextDeltaEvent (streaming)
                   yield ToolExecutionEvent
                   yield CompactionEvent (auto-trigger)
                   → consumer dispatch
```

**关键设计**：
- `run_agent_loop()` 是**纯函数 async 生成器**，不持有状态
- 每步 yield `AgentEvent`（模型请求、响应 delta、工具执行、错误、压缩）
- `AgentHarness` 包装纯循环为有状态多转接口（持有消息历史、取消状态、队列）
- **Steering 队列**：循环中中途注入（interrupt-and-redirect）
- **Follow-up 队列**：循环结束后触发新转
- **Step 级超时**：每个 provider 流步骤独立超时

```python
async for event in run_agent_loop(
    provider, messages, max_steps, tools, policy,
    steer_queue=steer_queue,  # 中途注入
    compact=True,             # 自动压缩
    compact_max_tokens=0,     # token 阈值
):
    if isinstance(event, ModelResponseEvent):
        console.print(event.content, end="")
    elif isinstance(event, ToolExecutionEvent):
        display_tool_event(event)
```

**优势**：可组合、惰性求值、可打断、纯函数易测试  
**劣势**：生成器状态管理需谨慎（通过 Harness 包装解决）

---

## 3. 消息与历史管理对比

### 3.1 Pi — 分支摘要

- 消息存储为结构化记录，带类型标记
- **分支触发摘要**：对话分支时旧分支被摘要化
- 摘要消息替换原始内容但保留元数据
- 系统消息始终保留

### 3.2 Tau — Token 预算自动压缩

- 内存中消息列表存储
- **自动压缩**：token 预算阈值触发
- 保留系统消息 + 最近 N 条消息
- 压缩区域替换为 token 占位符
- 压缩条目独立记录用于审计

### 3.3 Hermes-Agent — ContextManager

- 中心 `ContextManager` 持有消息历史
- `ContextCompressor` 支持 LLM 语义摘要
- 工具调用历史独立跟踪
- 支持多轮对话与历史裁剪

### 3.4 OpenCode — 上下文窗口管理

- 通过上下文窗口抽象管理消息
- Provider 特定消息格式转换
- 工具结果独立跟踪
- 会话持久化通过 SQLite

### 3.5 AgentsX — CJK-Aware 压缩 + 双存储

- `AgentMessage` dataclass 存储消息
- **CJK-aware token 估算**：拉丁字符 ~4 chars/token，CJK ~1.5 chars/token
  ```python
  def estimate_tokens(text: str) -> int:
      # 区分 Latin / CJK / whitespace 三类字符，分别用不同速率
      cjk_chars = count_if("一" <= ch <= "鿿" or ...)
      latin_chars = count_if(cat.startswith("L") and ch > "\x7f")
      return cjk / 1.5 + latin / 4 + ws / 8
  ```
- **自动压缩**：token 数量 **或** 消息数量任一超阈值即触发
- **LLM 摘要器**（可选）：占位符替换为语义摘要
- **Append-only 压缩审计**：压缩条目独立记录，支持 replay
- **双存储后端**：JSONL 文件树 (默认) + SQLite FTS5 (可选)
- **分支支持**：会话分支 + 消息历史复制

**差异化优势**：CJK-aware token 估算是五个项目中**唯一**支持混合字符集精确估算的。

---

## 4. 工具系统设计对比

### 4.1 Pi — 结构化 TypeScript 工具

- TypeScript struct 定义工具，显式参数
- 沙箱执行 (bubblewrap)
- 工具按能力分组 (read/write/exec)

### 4.2 Tau — ToolRegistry + JSON Schema

- `ToolRegistry` + JSON Schema 自动生成
- Toolset 支持 enable/disable 分组
- 权限分级 (read/write/exec/orchestration)
- 超时执行 + 输出限制

### 4.3 Hermes-Agent — ToolSpec + 插件

- `ToolSpec` 含描述、参数、执行函数
- 插件化工具发现
- 工具注册 + 验证
- 执行策略执行

### 4.4 OpenCode — Effect 化定义

- 工具定义为 Effect dispatch
- 配置文件中定义工具
- 插件系统支持自定义工具
- TUI 集成丰富

### 4.5 AgentsX — @tool() 装饰器 + 风险分级

```python
@tool(description="Read a file", toolset="read")
def tool_file_read(path: str, offset: int = 0) -> str: ...

@tool(description="Write a file", toolset="write", check_fn=lambda: has_write_permission())
def tool_file_write(path: str, content: str) -> str: ...
```

**关键设计**：
- `@tool()` 装饰器**自动生成 JSON Schema**（支持 Union、Optional、Literal、Enum、泛型容器）
- `ToolRegistry` 支持 toolset enable/disable
- **风险分级工具**：read → write → exec → web → orchestration → mcp
- `ToolResult` dataclass + 状态枚举 (SUCCESS/ERROR/BLOCKED)
- 输出截断保留**头部+尾部**（长日志可见开头和结尾）

**差异化优势**：`@tool()` 装饰器 + 自动 Schema 生成 + 风险分级组织是五个项目中**最符合人体工程学**的工具定义方式。

---

## 5. Provider/LLM 层对比

### 5.1 Pi — 多 Provider 接口

- TypeScript interface 定义 Provider 契约
- OpenAI、Anthropic 等具体实现
- SSE 流式
- 指数退避重试

### 5.2 Tau — Factory + Retry

- `create_provider()` 工厂函数
- 每个 LLM 的 Provider profile
- 可配置重试次数和延迟
- 斜杠记号解析模型

### 5.3 Hermes-Agent — 多 LLM 适配器

- 适配器模式适配不同 LLM API
- Context compressor 作为中间件
- YAML/JSON 配置 Provider

### 5.4 OpenCode — 配置驱动

- opencode.jsonc 中 Provider 配置
- LLM 抽象层
- 插件系统扩展新 Provider

### 5.5 AgentsX — Transport + Provider 双层架构

```
┌─────────────────────────────────────────┐
│          Provider Layer                  │
│  - Credential resolution                 │
│  - Client construction                   │
│  - Retry loops + backoff                 │
│  - Streaming orchestration               │
├─────────────────────────────────────────┤
│          Transport Layer                 │
│  - Message format conversion             │
│  - Request kwargs building               │
│  - Stream parsing → StreamEvent          │
├─────────────────────────────────────────┤
│          HTTP Client (httpx)             │
└─────────────────────────────────────────┘
```

**关键设计**：
- **双层分离**：Provider 处理凭证解析、重试、流式循环；Transport 处理消息格式化、请求构建、响应解析
- `ProviderTransport` ABC：`format_messages()`、`build_kwargs()`、`parse_stream()`
- `GenericProvider` 覆盖任何 OpenAI 兼容端点
- Provider catalog 从 TOML 文件加载
- **Provider profiles**：声明式元数据（认证、端点、能力、特性）
- 重试 + 分类错误恢复（上下文溢出 → 自动压缩 → 重试）

**差异化优势**：Transport/Provider 双层分离是五个项目中**最清晰**的架构设计，格式转换与编排完全解耦。

---

## 6. 安全模型对比

### 6.1 Pi — 沙箱 (Bubblewrap)

- Linux 沙箱 via bubblewrap
- 文件系统限制
- 网络隔离
- 资源限制

### 6.2 Tau — Policy 引擎

- `ExecutionPolicy` (ALLOW/PROMPT/FORBIDDEN)
- 工具调用模式匹配
- 文件路径验证

### 6.3 Hermes-Agent — 执行策略

- 工具执行策略
- 权限提示
- 可配置安全级别

### 6.4 OpenCode — 权限分级

- 每工具权限级别
- 用户确认提示
- JSON 配置

### 6.5 AgentsX — 4 层安全栈

```
Layer 1: ExecutionPolicy (fnmatch 模式匹配)
              ↓ ALLOW/PROMPT/FORBIDDEN
Layer 2: PathGuard (路径遍历检测 + 符号链接防护)
              ↓ 隔离工作区
Layer 3: CommandGuard (命令注入检测)
              ↓ rm -rf /, fork bomb, mkfs 检测
Layer 4: ResourceLimits (输出截断)
              ↓ head + tail 保留
```

**关键设计**：
- **ExecutionPolicy**：fnmatch 模式匹配 `"tool_name:{json_args}"`
- **PathGuard**：路径遍历检测 (`../`)、符号链接/接合点攻击防护、工作区边界强制
- **CommandGuard**：危险命令检测 (rm -rf /、fork bomb、mkfs) + shell 注入模式检测
- **ResourceLimits**：自动工具输出截断，每工具类型独立限制

**差异化优势**：四层安全栈 + 专用防护器是五个项目中**最全面**的安全模型。

---

## 7. 错误恢复对比

### 7.1 Pi — Retry + Fallback

- 指数退避重试
- Provider 故障时 fallback
- 优雅降级

### 7.2 Tau — Retry + 自动压缩

- 可配置重试次数
- 上下文溢出时自动压缩
- 压缩后重试

### 7.3 Hermes-Agent — Retry with Backoff

- 指数退避
- 错误分类
- Fallback providers

### 7.4 OpenCode — Retry Loops

- 瞬态失败重试
- 用户错误报告

### 7.5 AgentsX — 分类错误 + 智能恢复

```python
classify_api_error(error) → ClassifiedError {
    reason: THINKING_SIGNATURE  → should_fallback=True
    reason: CONTEXT_OVERFLOW    → should_compress=True, should_retry=True
    reason: RATE_LIMIT (429)    → delay=5.0s, should_retry=True
    reason: AUTH_ERROR (401)    → should_fallback=True
    reason: BILLING (402)       → should_fallback=True
    reason: SERVER_ERROR (5xx)  → delay=2.0s, should_retry=True, should_fallback=True
    reason: NETWORK_ERROR       → delay=2.0s, should_retry=True
    reason: UNKNOWN             → delay=1.0s, should_retry=True
}
```

**关键设计**：
- **优先级分类流水线**：thinking signature > context overflow > HTTP status > network heuristics > unknown
- **智能恢复动作**：should_retry、should_compress、should_fallback、delay_seconds、user_hint
- **循环内自动压缩**：上下文溢出 → 压缩 → 循环内直接重试（不中断用户）
- **RetryEvent** 可观测性

**差异化优势**：结构化错误分类 + 恢复动作是五个项目中**最智能**的错误处理。

---

## 8. 扩展性对比

### 8.1 Pi — 事件系统 + 钩子

```typescript
// AgentHarness 事件系统
harness.on("before_agent_start", async (event) => {
  // 修改系统提示词
  return { systemPrompt: modifiedPrompt };
});

harness.on("tool_call", async (event) => {
  // 拦截或修改工具调用
  return { block: false };
});

harness.on("tool_result", async (event) => {
  // 修改工具结果
  return { content: modifiedContent };
});
```

**关键设计**：
- **丰富的事件类型**：20+ 事件类型（before_agent_start、context、tool_call、tool_result、session_before_compact 等）
- **钩子可修改执行流**：某些钩子可返回结果修改行为（如修改系统提示词、拦截工具调用）
- **异步支持**：钩子处理器支持异步操作
- **类型安全**：TypeScript 类型定义确保事件和结果类型匹配

### 8.2 Tau — 事件监听器系统

```python
# AgentHarness 事件监听器
def on_event(event: AgentEvent):
    if event.type == "tool_execution_start":
        print(f"Tool started: {event.tool_name}")

unsub = harness.subscribe(on_event)
# later: unsub()
```

**关键设计**：
- **简单事件监听器**：通过 `subscribe()` 方法注册监听器
- **事件类型**：AgentStartEvent、AgentEndEvent、TurnStartEvent、TurnEndEvent、ToolExecutionStartEvent 等
- **纯观察者模式**：监听器只能观察事件，不能修改执行流
- **取消订阅**：返回取消订阅函数

### 8.3 Hermes-Agent — 丰富插件系统

```python
# 插件注册钩子
def register(ctx):
    ctx.register_hook("pre_tool_call", pre_tool_handler)
    ctx.register_hook("post_tool_call", post_tool_handler)
    
    # 注册工具
    ctx.register_tool(
        name="my_tool",
        toolset="my_toolset",
        schema={...},
        handler=my_tool_handler,
    )
    
    # 注册 CLI 命令
    ctx.register_cli_command("mycommand", "Help text", setup_fn)
    
    # 注册斜杠命令
    ctx.register_command("mycommand", handler, "Description")
```

**关键设计**：
- **多源插件发现**：bundled → user → project → pip entry_points
- **生命周期钩子**：20+ 钩子类型（pre_tool_call、post_tool_call、pre_llm_call、on_session_start 等）
- **工具注册**：插件可注册自定义工具
- **CLI 命令注册**：插件可注册 `hermes <subcommand>` 命令
- **斜杠命令注册**：插件可注册会话内斜杠命令
- **平台适配器注册**：插件可注册网关平台适配器
- **上下文引擎注册**：插件可替换内置上下文压缩器
- **图像/视频/TTS/STT 提供者注册**：插件可注册各种 AI 后端

### 8.4 OpenCode — 插件架构 + Effect 钩子

```typescript
// 插件定义
export const plugin: Plugin = async (input, options) => ({
  // 事件钩子
  event: async ({ event }) => {
    // 处理事件
  },
  
  // 工具定义
  tool: {
    myTool: {
      description: "My custom tool",
      parameters: {...},
      execute: async (args) => {...},
    },
  },
  
  // 认证钩子
  auth: {
    provider: "my-provider",
    methods: [{ type: "api", label: "API Key", ... }],
  },
  
  // 聊天消息钩子
  "chat.message": async (input, output) => {
    // 修改消息
  },
  
  // 工具执行前钩子
  "tool.execute.before": async (input, output) => {
    // 修改工具参数
  },
});
```

**关键设计**：
- **函数式插件定义**：插件作为函数返回钩子对象
- **丰富的钩子类型**：event、config、tool、auth、provider、chat.message、chat.params、tool.execute.before/after 等
- **工具定义**：插件可定义自定义工具
- **认证钩子**：插件可添加 OAuth/API 认证流程
- **提供者钩子**：插件可扩展 LLM 提供者
- **实验性钩子**：消息转换、系统提示词转换、会话压缩等

### 8.5 AgentsX — Observer API + entry_points

```python
api = ExtensionAPI()
api.on(EVENT_ON_TOOL_CALL, handler)
api.on(EVENT_ON_MODEL_RESPONSE, streaming_handler)

# Auto-discovery via entry_points
api.load_entry_points()  # group="agentsx.extensions"
```

**关键设计**：
- **纯观察者模式**：扩展只能观察事件，不能修改执行流
- **7 个生命周期事件**：loop start/end、model request/response、tool call/result、error
- **异常隔离**：处理器异常不中断 Agent 循环
- **自动发现**：`entry_points(group="agentsx.extensions")`

---

## 9. 会话与持久化对比

### 9.1 Pi — 文件树会话

- 会话存储为文件树
- 元数据 JSON 格式
- 消息结构化存储

### 9.2 Tau — JSONL Append-Only

- JSONL 文件树 under `~/.tau/sessions/`
- O(1) 追加写入
- 活动会话内存缓存
- 分支支持

### 9.3 Hermes-Agent — 内存 + 可选

- 主要内存存储
- 可选持久化层
- 简单会话管理

### 9.4 OpenCode — SQLite 会话

- SQLite 会话存储
- 全文搜索支持
- 丰富会话查询

### 9.5 AgentsX — JSONL + SQLite 双后端

```
SessionBackend Protocol
    ├── JSONL file-tree (default, zero deps)
    │   ├── O(1) append writes
    │   ├── Memory cache (LRU)
    │   ├── Branch support
    │   └── grep-friendly plain text
    └── SQLite FTS5 (optional)
        ├── Full-text search
        ├── Structured queries
        └── Branch support
```

**关键设计**：
- `SessionBackend` 协议抽象
- **JSONL 后端**：零依赖、O(1) 追加写入、内存缓存、grep 友好
- **SQLite 后端**：FTS5 全文搜索、结构化查询
- 会话分支 + 消息历史复制
- **压缩条目 replay**：append-only 审计日志，消息在 replay 时替换

---

## 10. AgentsX 设计优势总结

### 10.1 AgentsX 做得更好的方面

| 设计领域 | AgentsX 方案 | 竞争优势 |
|---------|-------------|---------|
| **Agent Loop** | 纯 async 生成器 (ReAct) | 比 FSM 更可组合，可打断，惰性求值 |
| **Provider 层** | Transport/Provider 双层 | 格式转换与编排最清晰分离 |
| **工具系统** | @tool() 装饰器 + 自动 Schema | 最符合人体工程学的工具定义，风险分级 |
| **错误恢复** | 分类错误 + 智能恢复 | 结构化恢复动作，溢出自动压缩 |
| **上下文管理** | CJK-aware 压缩 | 唯一支持混合字符集 token 估算 |
| **安全模型** | 4 层安全栈 | 最全面的安全防御 |
| **会话存储** | JSONL + SQLite 双后端 | 零依赖默认 + 强大可选后端 |
| **扩展性** | Observer API + entry_points | 安全观察，不修改执行流 |

### 10.2 AgentsX 可借鉴的方向

| 来源 | 借鉴点 | 应用方式 |
|------|--------|---------|
| **Pi** | 沙箱执行 (bubblewrap) | 比 AgentsX 的路径/命令防护更强的隔离 |
| **OpenCode** | Effect 函数式模式 | 提高可测试性 |
| **Tau** | 3 层架构分离 | Agent Brain 与应用层更清晰分离 |
| **Pi** | 分支摘要粒度 | 可补充 AgentsX 的压缩策略 |
| **Tau** | 并发工具执行 | 当前 AgentsX 工具顺序执行，可探索并行 |

### 10.3 其他项目可借鉴 AgentsX 的方向

| 目标 | 借鉴点 | 影响 |
|------|--------|------|
| **全部** | CJK-aware token 估算 | CJK 语言更好的上下文管理 |
| **全部** | Transport/Provider 双层 | 更清晰的 Provider 抽象 |
| **全部** | @tool() 装饰器 | 更简洁的工具定义 |
| **全部** | 分类错误恢复 | 更智能的错误处理 |
| **全部** | 4 层安全栈 | 更全面的安全防护 |
| **全部** | JSONL + SQLite 双后端 | 灵活性与零依赖兼得 |

---

## 11. 架构对比图

```
┌──────────────────────────────────────────────────────────────────┐
│                        Pi (TypeScript FSM)                               │
│  UserInput → FSM State → LLM → Tools → ContextUpdate → Loop     │
│  [Branch-summarize] [Sandbox] [Multi-provider]                   │
├──────────────────────────────────────────────────────────────────┤
│                        Tau (Python Events)                         │
│  UserInput → Context → LLM Stream → Tool Queue → Execute        │
│  [Auto-compact] [Policy] [JSONL sessions] [Retry]                │
├──────────────────────────────────────────────────────────────────┤
│                     Hermes-Agent (Python Events)                 │
│  Event Bus → Agent Loop → LLM → Tool Call → Event Emit          │
│  [ContextCompressor] [ToolPlugin] [Multi-LLM]                    │
├──────────────────────────────────────────────────────────────────┤
│                     OpenCode (TS Effects)                        │
│  Intent → Effect → LLM → Tool Effect → Result → Continue        │
│  [Plugin system] [TUI] [SQLite sessions] [Config-driven]         │
├──────────────────────────────────────────────────────────────────┤
│                     AgentsX (Python Async Gen)                   │
│  run_agent_loop() → yield AgentEvent → consumer dispatch        │
│  [CJK compaction] [2-layer provider] [@tool()] [4-layer sec]    │
│  [Classified error] [JSONL+SQLite] [Observer API]                │
└──────────────────────────────────────────────────────────────────┘
```

---

## 12. 结论

AgentsX 的 Harness 设计是对 Pi（分支摘要、状态机清晰度）、Tau（自动压缩、JSONL 会话、重试）、Hermes-Agent（事件驱动可观测性、工具插件）和 OpenCode（Effect 系统、插件架构）最佳模式的**有意识综合**，同时引入了**独特创新**：

1. **CJK-aware 上下文压缩** — 无竞品支持混合字符集 token 化
2. **Transport/Provider 双层** — 五个项目中最干净的 Provider 抽象
3. **@tool() 装饰器 + 自动 Schema** — 最符合人体工程学的工具定义
4. **分类错误恢复** — 结构化恢复动作 vs 简单重试
5. **4 层安全栈** — 全面的纵深防御
6. **双会话后端** — 零依赖默认 + 强大可选

主要改进方向为**沙箱执行**（Pi 的 bubblewrap 模型）和**函数式 Effect 模式**（OpenCode 的可测试性优势），两者均可增量采用。
