# 添加 `GROK_WEB_SEARCH_TOOL` 环境变量配置

> Status: TODO（待实施）
> Triggered by: v2.2.0 后实测发现代理 `ai.huan666.de` `/responses` + reasoning 模型时 payload 含 `tools: [{"type": "web_search"}]` 会被代理返回 `400 "Multiple web search tools are not supported"`。

## 问题

代理 `ai.huan666.de`（chenyme/grok2api 实现）在 reasoning 模型路径上**自动注入** web_search 工具。我们 payload 里再传 `tools: [{type: "web_search"}]` 时，server 端 tool 数变成 2 → 报错 400。

实测 4 格行为矩阵（model × tools 是否传）：

| 端点 + 模型 | 带 tools | 不带 tools |
|---|---|---|
| 官方 `api.x.ai` + 任意 | ✅ 搜 | ❌ 不搜（模型不主动搜） |
| 代理 + `grok-4.20-fast` | ✅ 搜（2 annotations） | ✅ 搜（2 annotations） |
| 代理 + `grok-4.20-reasoning` | ❌ 400 "Multiple web search tools" | ✅ 搜（4 annotations + web_search_call=3） |

结论：是否传 `tools` 是唯一变量，但最优值因 endpoint × model 而异。无单一全局策略。

## 方案

新增环境变量 `GROK_WEB_SEARCH_TOOL`（bool，默认 `true`），用户按部署场景显式声明。

### 用户使用方式

```jsonc
// 官方 / 代理 + fast：不写或显式 true
{
  "env": {
    "GROK_API_URL": "https://api.x.ai/v1",
    "GROK_API_KEY": "xai-...",
    "GROK_MODEL": "grok-4-fast"
    // GROK_WEB_SEARCH_TOOL 不写 = 默认 true
  }
}

// 代理 + reasoning：显式关闭
{
  "env": {
    "GROK_API_URL": "https://ai.huan666.de/v1",
    "GROK_API_KEY": "sk-...",
    "GROK_MODEL": "grok-4.20-reasoning",
    "GROK_WEB_SEARCH_TOOL": "false"
  }
}
```

### 决策原因（与 try-fallback 自动重试方案对比）

| 维度 | 配置开关（本方案） | try-fallback 重试 |
|---|---|---|
| 代码复杂度 | 低（一个 env var + if） | 中（异常捕获 + 字符串匹配 + 重试） |
| 失效风险 | 无 | 代理升级改错误文案后静默失效 |
| 可预测性 | 高（一次 query 一个 HTTP） | 低（命中 fallback 时多一次） |
| 用户感知 | 显式声明 | 隐式自动恢复 |
| 配置友好性 | 需要用户知道何时关 | 零配置 |

选**配置开关**：清晰 > 自动恢复，避免依赖代理错误文案这种隐式契约。

## 实施

### 1. `src/grok_search/config.py`

`Config` 类新增 property：

```python
@property
def web_search_tool_enabled(self) -> bool:
    return os.getenv("GROK_WEB_SEARCH_TOOL", "true").lower() in ("true", "1", "yes")
```

`get_config_info()` 返回字典中追加 `"GROK_WEB_SEARCH_TOOL": self.web_search_tool_enabled`。

**位置要求**：放在 try/except 之外的字段块中（与 `GROK_DEBUG`、`TAVILY_ENABLED` 同列，参见 `config.py:182` 之后的字段），**不要**放在 try 块里——该 property 不依赖 `grok_api_url` / `grok_api_key`，不应被配置错误吞掉。

### 2. `src/grok_search/providers/grok.py`

`GrokSearchProvider.search` 内 payload 构造：

```python
payload = {
    "model": self.model,
    "input": [
        {"role": "system", "content": search_prompt},
        {"role": "user", "content": time_context + query + platform_prompt},
    ],
}
if config.web_search_tool_enabled:
    payload["tools"] = [{"type": "web_search"}]
```

**flag 与 per-call `model` 参数的关系**：`web_search()` MCP 工具（`server.py:135`）允许调用方按次覆盖模型，但 `web_search_tool_enabled` 是**全局 env**，不随 per-call model 切换。这是有意设计（按部署画像配置），README 必须明示这一点。

### 3. 测试

#### 单测 `tests/test_provider_payload.py`（新文件）

mock httpx，断言 payload 内容：

- `GROK_WEB_SEARCH_TOOL=true`（或未设）→ payload 含 `tools: [{type: "web_search"}]`
- `GROK_WEB_SEARCH_TOOL=false` → payload 不含 `tools` 字段
- 其他 truthy 值（`1`, `yes`, `TRUE`, `True`）正确解析为 true
- 其他 falsy 值（`false`, `0`, `no`, `FALSE`）正确解析为 false
- 未知值视为 false（保守）

注意：`config` 是单例，但 `web_search_tool_enabled` 是直接 `os.getenv()`（无缓存，参见 `config.py` 中只有 `_cached_model` 走缓存路径），测试用 `monkeypatch.setenv()` 即可，**无需**清理任何 `config._cached_*` 字段。

#### 集成测试 `tests/test_extract.py` 内已有 fixture，无需更新。

#### 真实 HTTP 验证（手测）

`tests/manual_responses.py` 在 `_run_one()` 之前用 `os.environ["GROK_WEB_SEARCH_TOOL"]` 覆盖 flag（property 无缓存，覆盖即时生效），跑完恢复。

当前 harness 单 profile 仅一个模型（`tests/manual_responses.py:37-43`），6 行矩阵需要 **2 次重跑**：每次覆盖 `OFFICIAL_GROK_MODEL` / `PROXY_GROK_MODEL` 后重启脚本。验证时**必须记录 annotations 数**，对称行也要核对（避免代理两种值看似 OK 但隐性差异）。

| 端点 | 模型 | GROK_WEB_SEARCH_TOOL | 期望 |
|---|---|---|---|
| 官方 | reasoning | true（默认） | OK，annotations >= 3 |
| 官方 | reasoning | false | OK 但 annotations == 0（模型不搜） |
| 代理 | fast | true | OK，记录 annotations 数 N1 |
| 代理 | fast | false | OK，annotations 数应接近 N1（代理强注入，允许小幅波动） |
| 代理 | reasoning | true | 400 "Multiple web search tools" |
| 代理 | reasoning | false | OK，annotations >= 3 |

### 4. README 更新

`README.md` **和** `docs/README_EN.md` 配置环境变量表均新增 `GROK_WEB_SEARCH_TOOL` 行，并补一段说明：

> `GROK_WEB_SEARCH_TOOL`（可选，默认 `true`）：是否在 `/responses` payload 中注册 `web_search` 工具。**按部署画像配置**，不随单次调用的 `model` 参数变化。
> - 官方 `api.x.ai`：必须设为 `true`，否则模型不会主动搜索
> - 代理 `ai.huan666.de` + fast 模型：两种值皆可
> - 代理 `ai.huan666.de` + reasoning 模型：必须设为 `false`，否则代理会因"Multiple web search tools"返回 400

### 4.1 工具描述同步（`server.py:121`）

`web_search` MCP 工具的 description 当前写"with the built-in web_search tool"（`server.py:121`），flag=false 时该承诺不再准确。改为中性表述，例如 "via Grok's Responses API; web search is enabled when the deployment supports it (controlled by `GROK_WEB_SEARCH_TOOL`)"。

### 5. 版本

`web_search` 工具 `meta.version` 2.2.0 → **2.3.0**（行为可配置，向后兼容）。

## 验收

- [ ] `config.py` 新增 property（无缓存）+ `get_config_info()` 在 try/except 之外暴露
- [ ] `grok.py` `search()` 内根据 flag 决定是否注入 `tools`
- [ ] 单测覆盖 true/false/各种 truthy-falsy 字符串（含 `1`/`yes`/`TRUE`/`0`/`no`/`FALSE`/未知值）
- [ ] 真实 HTTP 跑通 6 个组合（含 annotations 数对称核对）
- [ ] `README.md` + `docs/README_EN.md` 双语更新
- [ ] `server.py:121` `web_search` 工具 description 同步（去除"built-in"硬承诺）
- [ ] `web_search` `meta.version` 2.2.0 → 2.3.0
- [ ] codex 审查无 blocking
- [ ] commit message 写明 v2.3.0 意图与代理 reasoning 兼容性问题

## 备注

- 配置名 `GROK_WEB_SEARCH_TOOL` 选择理由：与现有 `GROK_DEBUG`、`TAVILY_ENABLED` 风格一致；显意（不是 `GROK_OMIT_TOOLS` 这种负向命名）；预留扩展（未来 xAI 加新 tool 类型时可以变成 `GROK_TOOLS=web_search,code_interpreter` 之类）。
- 如需进一步可扩展，后续可演进为 `GROK_TOOLS=web_search`（CSV）。但当前 xAI Responses API 我们只用 web_search，没必要立即上 CSV。
- 对老 `/chat/completions` 路径无影响（已删除），仅作用于 `/responses`。
