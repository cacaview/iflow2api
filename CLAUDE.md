# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**iflow2api** 是一个将 iFlow CLI 的 AI 服务暴露为 OpenAI 兼容 API 的代理服务。

核心功能：
- 自动读取 iFlow CLI 的登录凭证 (`~/.iflow/settings.json`)
- 通过特殊 User-Agent (`iFlow-Cli`) 解锁 iFlow CLI 专属模型
- 提供 OpenAI 兼容的 API 端点

## Build & Run Commands

```bash
# 安装依赖
uv pip install -e .

# 运行服务
python -m iflow2api

# 或指定端口
python -c "import uvicorn; from iflow2api.app import app; uvicorn.run(app, host='0.0.0.0', port=8001)"

# 测试
curl http://localhost:8001/health
curl http://localhost:8001/v1/models
curl http://localhost:8001/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"glm-4.7","messages":[{"role":"user","content":"hi"}]}'
```

## Architecture

```
src/iflow2api/
├── __init__.py      # 包初始化
├── __main__.py      # CLI 入口
├── main.py          # 主入口
├── config.py        # iFlow 配置读取器 (从 ~/.iflow/settings.json)
├── proxy.py         # API 代理 (添加 user-agent: iFlow-Cli header)
└── app.py           # FastAPI 应用 (OpenAI 兼容端点)
```

## Key Implementation Details

### 解锁 iFlow CLI 专属模型

iFlow API 通过 User-Agent header 区分普通 API 调用和 CLI 调用：
- 普通调用：只能使用 glm-4.6 等基础模型
- CLI 调用 (`user-agent: iFlow-Cli`)：可使用 glm-4.7, deepseek-r1, kimi-k2 等高级模型

### 配置文件位置

- Windows: `C:\Users\<user>\.iflow\settings.json`
- Linux/Mac: `~/.iflow/settings.json`

关键字段：
- `apiKey`: API 密钥
- `baseUrl`: API 端点 (默认 https://apis.iflow.cn/v1)
- `selectedAuthType`: 认证类型 (oauth-iflow, api-key, openai-compatible)

## API Endpoints

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/v1/models` | GET | 获取可用模型列表 |
| `/v1/chat/completions` | POST | Chat Completions API |
| `/models` | GET | 兼容端点 |
| `/chat/completions` | POST | 兼容端点 |

## Dependencies

- FastAPI: Web 框架
- uvicorn: ASGI 服务器
- httpx: 异步 HTTP 客户端
- pydantic: 数据验证
