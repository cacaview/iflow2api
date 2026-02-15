# iflow2api

[English Documentation](README_EN.md) | 简体中文

将 iFlow CLI 的 AI 服务暴露为 OpenAI 兼容 API。

## 功能

- 自动读取 iFlow 配置文件 (`~/.iflow/settings.json`)
- 提供 OpenAI 兼容的 API 端点
- 支持流式和非流式响应
- 通过 `User-Agent: iFlow-Cli` 解锁 CLI 专属高级模型
- 内置 GUI OAuth 登录界面，无需安装 iFlow CLI
- 支持 OAuth token 自动刷新

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

### 登录方式（二选一）

#### 方式 1: 使用内置 GUI 登录（推荐）

无需安装 iFlow CLI，直接使用内置登录界面：

```bash
# 启动服务时会自动打开登录界面
python -m iflow2api
```

点击界面上的 "OAuth 登录" 按钮，完成登录即可。

#### 方式 2: 使用 iFlow CLI 登录

如果你已安装 iFlow CLI，可以直接使用：

```bash
# 安装 iFlow CLI
npm i -g @iflow-ai/iflow-cli

# 运行登录
iflow
```

### 配置文件

登录后配置文件会自动生成：
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
iflow2api/
├── __init__.py          # 包初始化
├── __main__.py          # CLI 入口 (python -m iflow2api)
├── main.py              # 主入口
├── config.py            # iFlow 配置读取器 (从 ~/.iflow/settings.json)
├── proxy.py             # API 代理 (添加 User-Agent header)
├── app.py               # FastAPI 应用 (OpenAI 兼容端点)
├── oauth.py             # OAuth 认证逻辑
├── oauth_login.py       # OAuth 登录处理器
├── token_refresher.py   # OAuth token 自动刷新
├── settings.py          # 应用配置管理
└── gui.py               # GUI 界面
```

## 常见问题

### Q: 提示 "iFlow 未登录"

确保已完成登录：
- **GUI 方式**：点击界面上的 "OAuth 登录" 按钮
- **CLI 方式**：运行 `iflow` 命令并完成登录

检查 `~/.iflow/settings.json` 文件是否存在且包含 `apiKey` 字段。

### Q: 模型调用失败

1. 确认使用的模型 ID 正确（参考上方模型列表）
2. 检查 iFlow 账户是否有足够的额度
3. 查看服务日志获取详细错误信息

### Q: 如何更新模型列表

模型列表硬编码在 `proxy.py` 中，来源于 iflow-cli 源码。如果 iFlow 更新了支持的模型，需要手动更新此列表。

### Q: 是否必须安装 iFlow CLI？

不是。从 v0.4.1 开始，项目内置了 GUI OAuth 登录功能，无需安装 iFlow CLI 即可使用。

### Q: GUI 登录和 CLI 登录的配置可以共用吗？

可以。两种登录方式都使用同一个配置文件 `~/.iflow/settings.json`，GUI 登录后命令行模式可以直接使用，反之亦然。

### Q: macOS 上下载的应用无法执行

如果在 macOS 上通过浏览器下载 `iflow2api.app` 后无法执行，通常有两个原因：

1. **缺少执行权限**：可执行文件没有执行位
2. **隔离标记**：文件带有 `com.apple.quarantine` 属性

**修复方法**：

```bash
# 移除隔离标记
xattr -cr iflow2api.app

# 添加执行权限
chmod +x iflow2api.app/Contents/MacOS/iflow2api
```

执行上述命令后，应用就可以正常运行了。

## License

MIT
