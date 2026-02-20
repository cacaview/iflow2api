# iflow2api

[English Documentation](README_EN.md) | 简体中文

将 iFlow CLI 的 AI 服务暴露为 OpenAI 兼容 API。

##### **我们在[这里](https://github.com/cacaview/iflow2api-sdk)发布了我们的SDK！欢迎来进行使用！**

## 功能

### 核心功能

- 自动读取 iFlow 配置文件 (`~/.iflow/settings.json`)
- 提供 OpenAI 兼容的 API 端点
- 支持流式和非流式响应
- 通过 `User-Agent: iFlow-Cli` 解锁 CLI 专属高级模型
- 内置 GUI OAuth 登录界面，无需安装 iFlow CLI
- 支持 OAuth token 自动刷新
- 兼容 Anthropic Messages API，可直接对接 Claude Code

### 桌面应用

- **系统托盘** - 最小化到托盘、托盘菜单、状态显示
- **跨平台开机自启动** - 支持 Windows (注册表) / macOS (LaunchAgent) / Linux (XDG autostart)
- **暗色主题** - 支持亮色/暗色/跟随系统主题切换
- **多语言支持** - 中英文界面切换

### 管理功能

- **Web 管理界面** - 独立管理页面，支持远程管理和登录认证
- **多实例管理** - 支持多个服务实例、不同端口配置
- **API 文档页面** - Swagger UI (`/docs`) + ReDoc (`/redoc`)
- **并发控制** - 可配置 API 并发数，控制同时处理的请求数量

### 高级功能

- **Vision 支持** - 图像输入、Base64 编码、URL 支持
- **配置加密** - 敏感配置加密存储
- **Docker 支持** - 提供 Dockerfile 和 docker-compose.yml

## 支持的模型

### 文本模型

| 模型 ID                | 名称              | 说明                      |
| ---------------------- | ----------------- | ------------------------- |
| `glm-4.6`            | GLM-4.6           | 智谱 GLM-4.6              |
| `glm-4.7`            | GLM-4.7           | 智谱 GLM-4.7              |
| `glm-5`              | GLM-5             | 智谱 GLM-5 (推荐)         |
| `iFlow-ROME-30BA3B`  | iFlow-ROME-30BA3B | iFlow ROME 30B (快速)     |
| `deepseek-v3.2-chat` | DeepSeek-V3.2     | DeepSeek V3.2 对话模型    |
| `qwen3-coder-plus`   | Qwen3-Coder-Plus  | 通义千问 Qwen3 Coder Plus |
| `kimi-k2`            | Kimi-K2           | Moonshot Kimi K2          |
| `kimi-k2-thinking`   | Kimi-K2-Thinking  | Moonshot Kimi K2 思考模型 |
| `kimi-k2.5`          | Kimi-K2.5         | Moonshot Kimi K2.5        |
| `kimi-k2-0905`       | Kimi-K2-0905      | Moonshot Kimi K2 0905     |
| `minimax-m2.5`       | MiniMax-M2.5      | MiniMax M2.5              |

### 视觉模型

| 模型 ID         | 名称        | 说明                     |
| --------------- | ----------- | ------------------------ |
| `qwen-vl-max` | Qwen-VL-Max | 通义千问 VL Max 视觉模型 |

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

服务默认运行在 `http://localhost:28000`

### 自定义端口

```bash
python -c "import uvicorn; from iflow2api.app import app; uvicorn.run(app, host='0.0.0.0', port=8001)"
```

## API 端点

| 端点                     | 方法 | 说明                                            |
| ------------------------ | ---- | ----------------------------------------------- |
| `/health`              | GET  | 健康检查                                        |
| `/v1/models`           | GET  | 获取可用模型列表                                |
| `/v1/chat/completions` | POST | Chat Completions API (OpenAI 格式)              |
| `/v1/messages`         | POST | Messages API (Anthropic 格式，Claude Code 兼容) |
| `/models`              | GET  | 兼容端点 (不带 /v1 前缀)                        |
| `/chat/completions`    | POST | 兼容端点 (不带 /v1 前缀)                        |
| `/docs`                | GET  | Swagger UI API 文档                             |
| `/redoc`               | GET  | ReDoc API 文档                                  |
| `/admin`               | GET  | Web 管理界面                                    |

## Docker 部署

镜像已发布到 Docker Hub，支持滚动发布：

```bash
# 使用最新稳定版（推荐）
docker pull cacaview/iflow2api:latest

# 使用开发版（体验最新功能）
docker pull cacaview/iflow2api:edge

# 使用特定版本
docker pull cacaview/iflow2api:1.1.5
```

或使用 docker-compose：

```bash
docker-compose up -d
```

详细部署文档请参考 [Docker 部署指南](docs/DOCKER.md)。

## Web 管理界面

iflow2api 提供了独立的 Web 管理界面，支持远程管理：

- 访问地址：`http://localhost:28000/admin`
- 默认用户名/密码：`admin` / `admin`

**功能特性**：

- 实时服务状态监控
- 多实例管理
- 远程启动/停止服务
- 配置管理

## 高级配置

### 思考链（Chain of Thought）设置

某些模型（如 GLM-5、Kimi-K2-Thinking）支持思考链功能，会在响应中返回 `reasoning_content` 字段，展示模型的推理过程。

**配置方式**

编辑配置文件 `~/.iflow2api/config.json`：

```json
{
  "preserve_reasoning_content": true
}
```

**配置说明**

| 配置值            | 行为                                                    | 适用场景                           |
| ----------------- | ------------------------------------------------------- | ---------------------------------- |
| `false`（默认） | 将 `reasoning_content` 合并到 `content` 字段        | OpenAI 兼容客户端，只需最终回答    |
| `true`          | 保留 `reasoning_content` 字段，同时复制到 `content` | 需要分别显示思考过程和回答的客户端 |

**响应格式对比**

默认模式（`preserve_reasoning_content: false`）：

```json
{
  "choices": [{
    "message": {
      "content": "思考过程...\n\n最终回答..."
    }
  }]
}
```

保留模式（`preserve_reasoning_content: true`）：

```json
{
  "choices": [{
    "message": {
      "content": "最终回答...",
      "reasoning_content": "思考过程..."
    }
  }]
}
```

> **注意**：即使开启保留模式，`content` 字段也会被填充，以确保只读取 `content` 的客户端能正常工作。

## 客户端配置示例

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:28000/v1",
    api_key="not-needed"  # API Key 从 iFlow 配置自动读取
)

# 非流式请求
response = client.chat.completions.create(
    model="glm-5",
    messages=[{"role": "user", "content": "你好！"}]
)
print(response.choices[0].message.content)

# 流式请求
stream = client.chat.completions.create(
    model="glm-5",
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
curl http://localhost:28000/v1/models

# 非流式请求
curl http://localhost:28000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-5",
    "messages": [{"role": "user", "content": "你好！"}]
  }'

# 流式请求
curl http://localhost:28000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-5",
    "messages": [{"role": "user", "content": "你好！"}],
    "stream": true
  }'
```

### Claude Code

iflow2api 提供了 Anthropic 兼容的 `/v1/messages` 端点，可以直接对接 Claude Code。

**1. 配置环境变量**

在 `~/.zshrc`（或 `~/.bashrc`）中添加：

```bash
export ANTHROPIC_BASE_URL="http://localhost:28000"
export ANTHROPIC_MODEL="glm-5" # kimi-k2.5, minimax-m2.5
export ANTHROPIC_API_KEY="sk-placeholder"  # 任意非空值即可，认证信息从 iFlow 配置自动读取
```

生效配置：

```bash
source ~/.zshrc
```

**2. 启动 iflow2api 服务**

```bash
python -m iflow2api
```

**3. 使用 Claude Code**

启动 Claude Code 后，使用 `/model` 命令切换到 iFlow 支持的模型：

```
/model glm-5
```

支持的模型 ID：`glm-5`、`deepseek-v3.2-chat`、`qwen3-coder-plus`、`kimi-k2-thinking`、`minimax-m2.5`、`kimi-k2.5`

> **注意**：如果不切换模型，Claude Code 默认使用 `claude-sonnet-4-5-20250929` 等模型名，代理会自动将其映射到 `glm-5`。你也可以直接使用默认模型，无需手动切换。

**工作原理**：Claude Code 向 `/v1/messages` 发送 Anthropic 格式请求 → iflow2api 将请求体转换为 OpenAI 格式 → 转发到 iFlow API → 将响应转换回 Anthropic SSE 格式返回给 Claude Code。

### 第三方客户端

本服务兼容以下 OpenAI 兼容客户端:

- **Claude Code**: 设置 `ANTHROPIC_BASE_URL=http://localhost:28000`（详见上方指南）
- **ChatGPT-Next-Web**: 设置 API 地址为 `http://localhost:28000`
- **LobeChat**: 添加 OpenAI 兼容提供商，Base URL 设为 `http://localhost:28000/v1`
- **Open WebUI**: 添加 OpenAI 兼容连接
- **其他 OpenAI SDK 兼容应用**

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      客户端请求                              │
│  (Claude Code / OpenAI SDK / curl / ChatGPT-Next-Web)      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    iflow2api 本地代理                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  /v1/chat/completions │ /v1/messages │ /v1/models │   │
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
├── gui.py               # GUI 界面
├── vision.py            # Vision 支持 (图像输入处理)
├── tray.py              # 系统托盘
├── autostart.py         # 开机自启动
├── i18n.py              # 国际化支持
├── crypto.py            # 配置加密
├── instances.py         # 多实例管理
├── server.py            # 服务器管理
├── web_server.py        # Web 服务器
├── updater.py           # 自动更新
└── admin/               # Web 管理界面
    ├── auth.py          # 管理界面认证
    ├── routes.py        # 管理界面路由
    ├── websocket.py     # WebSocket 通信
    └── static/          # 静态文件 (HTML/CSS/JS)
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
