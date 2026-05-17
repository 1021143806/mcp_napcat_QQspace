
# OpenAI 与 Anthropic 的 MCP 调用格式

## 先厘清两个层次

这个问题需要分两层来看：

### 1. MCP 协议本身 — **是一样的**

MCP（Model Context Protocol）是 Anthropic 发起并开源的标准协议，基于 **JSON-RPC 2.0**。无论你用哪家的模型，**MCP Client ↔ MCP Server** 之间的通信格式是统一的：

```json
// MCP 标准：调用工具
{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "tool_name", "arguments": {...}}, "id": 1}
```

这一层不存在差异。

### 2. AI 模型的 Tool Calling API 格式 — **不一样**

差异出现在 **模型 API 怎么定义和调用工具** 这一层：

| | **OpenAI** | **Anthropic** |
|---|---|---|
| 工具定义字段 | `tools[].function.parameters` | `tools[].input_schema` |
| 工具类型声明 | `"type": "function"` | 直接在 tools 数组中 |
| 模型返回调用 | `tool_calls[].function.name/arguments` | `content[].type="tool_use"`, 含 `name/input` |
| 参数描述 | JSON Schema（在 `function` 下） | JSON Schema（在顶层 `input_schema` 下） |

简单对比：

```json
// OpenAI 工具定义
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "parameters": { "type": "object", "properties": {...} }
  }
}

// Anthropic 工具定义
{
  "name": "get_weather",
  "input_schema": { "type": "object", "properties": {...} }
}
```

## 3. 所以关键在哪？

关键在 **MCP Client（宿主）** 这一层做了**格式转换/桥接**：

```
[MCP Server] ←标准MCP协议→ [MCP Client] ←各家API格式→ [AI Model]
```

- MCP Client 从 MCP Server 拿到统一格式的工具定义
- 然后翻译成 OpenAI 或 Anthropic 各自 API 要求的 tool calling 格式，喂给模型
- 模型返回的调用结果，再翻译回 MCP 标准格式发给 Server 执行

所以如果你在写 MCP Client 或做集成适配，**这层翻译逻辑是需要自己处理的**（或者用各家的 SDK，它们已经封装了）。

---

**总结一句话**：MCP 协议本身是统一的，但 OpenAI 和 Anthropic 各自的模型 API Tool Calling 格式不同，MCP Client 负责在中间做桥接翻译。你遇到的"格式不一样"大概率就是这个 API 层的差异。