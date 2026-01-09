# iflow2api

将 iFlow CLI 的 AI 服务暴露为 OpenAI 兼容 API。

## 功能

- 自动读取 iFlow CLI 的登录凭证 (`~/.iflow/settings.json`)
- 提供 OpenAI 兼容的 API 端点
- 支持流式和非流式响应
- 通过 `User-Agent: iFlow-Cli` 解锁 CLI 专属高级模型

## 支持的模型

| 模型 ID | 名称 | 说明 |
|---------|------|------|
| `glm-4.7` | GLM-4.7 | 智谱 GLM-4.7 (推荐) |
| `iFlow-ROME-30BA3B` | iFlow-ROME-30BA3B | iFlow ROME 30B (快速) |
| `deepseek-v3.2-chat` | DeepSeek-V3.2 | DeepSeek V3.2 对话模型 |
| `qwen3-coder-plus` | Qwen3-Coder-Plus | 通义千问 Qwen3 Coder Plus |
| `kimi-k2-thinking` | Kimi-K2-Thinking | Moonshot Kimi K2 思考模型 |
| `minimax-m2.1` | MiniMax-M2.1 | MiniMax M2.1 |
| `kimi-k2-0905` | Kimi-K2-0905 | Moonshot Kimi K2 0905 |

> 模型列表来源于 iflow-cli 源码，可能随 iFlow 更新而变化。

## 前置条件

1. 安装 iFlow CLI:
   ```bash
   npm i -g @iflow-ai/iflow-cli
   ```

2. 运行 `iflow` 并完成登录（选择 "Login with iFlow"）:
   ```bash
   iflow
   ```

3. 确认配置文件已生成:
   - Windows: `C:\Users\<用户名>\.iflow\settings.json`
   - Linux/Mac: `~/.iflow/settings.json`

## 安装

```bash
# 使用 uv (推荐)
uv pip install -e .

# 或使用 pip
pip install -e .
```

## 使用

### 启动服务

```bash
# 方式 1: 使用模块
python -m iflow2api

# 方式 2: 使用命令行
iflow2api
```

服务默认运行在 `http://localhost:8000`

### 自定义端口

```bash
python -c "import uvicorn; from iflow2api.app import app; uvicorn.run(app, host='0.0.0.0', port=8001)"
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/v1/models` | GET | 获取可用模型列表 |
| `/v1/chat/completions` | POST | Chat Completions API |
| `/models` | GET | 兼容端点 (不带 /v1 前缀) |
| `/chat/completions` | POST | 兼容端点 (不带 /v1 前缀) |

## 客户端配置示例

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"  # API Key 从 iFlow 配置自动读取
)

# 非流式请求
response = client.chat.completions.create(
    model="glm-4.7",
    messages=[{"role": "user", "content": "你好！"}]
)
print(response.choices[0].message.content)

# 流式请求
stream = client.chat.completions.create(
    model="glm-4.7",
    messages=[{"role": "user", "content": "写一首诗"}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### curl

```bash
# 获取模型列表
curl http://localhost:8000/v1/models

# 非流式请求
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4.7",
    "messages": [{"role": "user", "content": "你好！"}]
  }'

# 流式请求
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4.7",
    "messages": [{"role": "user", "content": "你好！"}],
    "stream": true
  }'
```

### 第三方客户端

本服务兼容以下 OpenAI 兼容客户端:

- **ChatGPT-Next-Web**: 设置 API 地址为 `http://localhost:8000`
- **LobeChat**: 添加 OpenAI 兼容提供商，Base URL 设为 `http://localhost:8000/v1`
- **Open WebUI**: 添加 OpenAI 兼容连接
- **其他 OpenAI SDK 兼容应用**

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      客户端请求                              │
│  (OpenAI SDK / curl / ChatGPT-Next-Web / LobeChat)         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    iflow2api 本地代理                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  /v1/chat/completions  │  /v1/models  │  /health   │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  1. 读取 ~/.iflow/settings.json 获取认证信息         │   │
│  │  2. 添加 User-Agent: iFlow-Cli 解锁高级模型          │   │
│  │  3. 转发请求到 iFlow API                            │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    iFlow API 服务                            │
│                https://apis.iflow.cn/v1                      │
└─────────────────────────────────────────────────────────────┘
```

## 工作原理

iFlow API 通过 `User-Agent` header 区分普通 API 调用和 CLI 调用:

- **普通 API 调用**: 只能使用基础模型
- **CLI 调用** (`User-Agent: iFlow-Cli`): 可使用 GLM-4.7、DeepSeek、Kimi 等高级模型

本项目通过在请求中添加 `User-Agent: iFlow-Cli` header，让普通 API 客户端也能访问 CLI 专属模型。

## 项目结构

```
src/iflow2api/
├── __init__.py      # 包初始化
├── __main__.py      # CLI 入口 (python -m iflow2api)
├── main.py          # 主入口
├── config.py        # iFlow 配置读取器
├── proxy.py         # API 代理 (添加 User-Agent header)
└── app.py           # FastAPI 应用
```

## 常见问题

### Q: 提示 "iFlow 未登录"

确保已运行 `iflow` 命令并完成登录，检查 `~/.iflow/settings.json` 文件是否存在且包含 `apiKey` 字段。

### Q: 模型调用失败

1. 确认使用的模型 ID 正确（参考上方模型列表）
2. 检查 iFlow 账户是否有足够的额度
3. 查看服务日志获取详细错误信息

### Q: 如何更新模型列表

模型列表硬编码在 `proxy.py` 中，来源于 iflow-cli 源码。如果 iFlow 更新了支持的模型，需要手动更新此列表。

## License

MIT
