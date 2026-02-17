# iflow2api

English Documentation | [简体中文](README.md)

Exposes iFlow CLI's AI services as an OpenAI-compatible API.

## Features

### Core Features

- Automatically reads iFlow configuration file (`~/.iflow/settings.json`)
- Provides OpenAI-compatible API endpoints
- Supports both streaming and non-streaming responses
- Unlocks CLI-exclusive advanced models via `User-Agent: iFlow-Cli`
- Built-in GUI OAuth login interface - no need to install iFlow CLI
- Supports automatic OAuth token refresh
- Compatible with Anthropic Messages API, can directly connect to Claude Code

### Desktop Application

- **System Tray** - Minimize to tray, tray menu, status display
- **Cross-platform Auto-start** - Windows (Registry) / macOS (LaunchAgent) / Linux (XDG autostart)
- **Dark Theme** - Light/Dark/Follow system theme switching
- **Multi-language Support** - English/Chinese interface switching

### Management Features

- **Web Admin Interface** - Independent management page, remote management and authentication
- **Multi-instance Management** - Multiple service instances, different port configurations
- **API Documentation** - Swagger UI (`/docs`) + ReDoc (`/redoc`)
- **Rate Limiting** - Client request throttling, configurable rules

### Advanced Features

- **Vision Support** - Image input, Base64 encoding, URL support
- **Config Encryption** - Encrypted storage of sensitive configuration
- **Docker Support** - Dockerfile and docker-compose.yml provided

## Supported Models

### Text Models

| Model ID               | Name              | Description                       |
| ---------------------- | ----------------- | --------------------------------- |
| `glm-4.6`             | GLM-4.6           | Zhipu GLM-4.6                     |
| `glm-4.7`             | GLM-4.7           | Zhipu GLM-4.7                     |
| `glm-5`               | GLM-5             | Zhipu GLM-5 (Recommended)         |
| `iFlow-ROME-30BA3B`   | iFlow-ROME-30BA3B | iFlow ROME 30B (Fast)             |
| `deepseek-v3.2-chat`  | DeepSeek-V3.2     | DeepSeek V3.2 Chat Model          |
| `qwen3-coder-plus`    | Qwen3-Coder-Plus  | Tongyi Qianwen Qwen3 Coder Plus   |
| `kimi-k2`             | Kimi-K2           | Moonshot Kimi K2                  |
| `kimi-k2-thinking`    | Kimi-K2-Thinking  | Moonshot Kimi K2 Thinking Model   |
| `kimi-k2.5`           | Kimi-K2.5         | Moonshot Kimi K2.5                |
| `kimi-k2-0905`        | Kimi-K2-0905      | Moonshot Kimi K2 0905             |
| `minimax-m2.5`        | MiniMax-M2.5      | MiniMax M2.5                      |

### Vision Models

| Model ID               | Name              | Description                       |
| ---------------------- | ----------------- | --------------------------------- |
| `qwen-vl-max`         | Qwen-VL-Max       | Tongyi Qianwen VL Max Vision Model |

> Model list is sourced from iflow-cli source code and may change with iFlow updates.

## Prerequisites

### Login Method (Choose One)

#### Method 1: Use Built-in GUI Login (Recommended)

No need to install iFlow CLI, just use the built-in login interface:

```bash
# Login interface will open automatically when starting the service
python -m iflow2api
```

Click the "OAuth Login" button on the interface to complete the login.

#### Method 2: Use iFlow CLI Login

If you have already installed iFlow CLI:

```bash
# Install iFlow CLI
npm i -g @iflow-ai/iflow-cli

# Run login
iflow
```

### Configuration File

After logging in, the configuration file will be automatically generated:

- Windows: `C:\Users\<username>\.iflow\settings.json`
- Linux/Mac: `~/.iflow/settings.json`

## Installation

```bash
# Using uv (recommended)
uv pip install -e .

# Or using pip
pip install -e .
```

## Usage

### Start the Service

```bash
# Method 1: Using module
python -m iflow2api

# Method 2: Using command line
iflow2api
```

The service runs by default on `http://localhost:28000`

### Custom Port

```bash
python -c "import uvicorn; from iflow2api.app import app; uvicorn.run(app, host='0.0.0.0', port=8001)"
```

## API Endpoints

| Endpoint                  | Method | Description                                         |
| ------------------------- | ------ | --------------------------------------------------- |
| `/health`               | GET    | Health check                                        |
| `/v1/models`            | GET    | Get available model list                            |
| `/v1/chat/completions`  | POST   | Chat Completions API (OpenAI format)                |
| `/v1/messages`          | POST   | Messages API (Anthropic format, Claude Code compatible) |
| `/models`               | GET    | Compatible endpoint (without /v1 prefix)            |
| `/chat/completions`     | POST   | Compatible endpoint (without /v1 prefix)            |
| `/docs`                 | GET    | Swagger UI API Documentation                        |
| `/redoc`                | GET    | ReDoc API Documentation                             |
| `/admin`                | GET    | Web Admin Interface                                 |

## Docker Deployment

```bash
# Using docker-compose
docker-compose up -d

# Or build and run directly
docker build -t iflow2api .
docker run -d -p 28000:28000 -v ~/.iflow:/home/appuser/.iflow:ro iflow2api
```

For detailed deployment instructions, see [Docker Deployment Guide](docs/DOCKER.md).

## Web Admin Interface

iflow2api provides an independent web admin interface for remote management:

- URL: `http://localhost:28000/admin`
- Default username/password: `admin` / `admin`

**Features**:
- Real-time service status monitoring
- Multi-instance management
- Remote start/stop services
- Configuration management

## Advanced Configuration

### Chain of Thought (CoT) Settings

Some models (such as GLM-5, Kimi-K2-Thinking) support Chain of Thought functionality, returning a `reasoning_content` field in the response that shows the model's reasoning process.

**Configuration**

Edit the configuration file `~/.iflow2api/config.json`:

```json
{
  "preserve_reasoning_content": true
}
```

**Configuration Options**

| Value | Behavior | Use Case |
| ----- | -------- | -------- |
| `false` (default) | Merges `reasoning_content` into the `content` field | OpenAI-compatible clients that only need the final answer |
| `true` | Preserves `reasoning_content` field, also copies to `content` | Clients that need to display reasoning process and answer separately |

**Response Format Comparison**

Default mode (`preserve_reasoning_content: false`):
```json
{
  "choices": [{
    "message": {
      "content": "Reasoning process...\n\nFinal answer..."
    }
  }]
}
```

Preserve mode (`preserve_reasoning_content: true`):
```json
{
  "choices": [{
    "message": {
      "content": "Final answer...",
      "reasoning_content": "Reasoning process..."
    }
  }]
}
```

> **Note**: Even with preserve mode enabled, the `content` field will still be populated to ensure clients that only read `content` work correctly.

## Client Configuration Examples

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:28000/v1",
    api_key="not-needed"  # API Key automatically read from iFlow configuration
)

# Non-streaming request
response = client.chat.completions.create(
    model="glm-5",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)

# Streaming request
stream = client.chat.completions.create(
    model="glm-5",
    messages=[{"role": "user", "content": "Write a poem"}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### curl

```bash
# Get model list
curl http://localhost:28000/v1/models

# Non-streaming request
curl http://localhost:28000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-5",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# Streaming request
curl http://localhost:28000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-5",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

### Claude Code

iflow2api provides an Anthropic-compatible `/v1/messages` endpoint that can directly connect to Claude Code.

**1. Configure Environment Variables**

Add to `~/.zshrc` (or `~/.bashrc`):

```bash
export ANTHROPIC_BASE_URL="http://localhost:28000"
export ANTHROPIC_MODEL="glm-5" # kimi-k2.5, minimax-m2.5
export ANTHROPIC_API_KEY="sk-placeholder"  # Any non-empty value, auth info read from iFlow config
```

Apply the configuration:

```bash
source ~/.zshrc
```

**2. Start iflow2api Service**

```bash
python -m iflow2api
```

**3. Use Claude Code**

After starting Claude Code, use the `/model` command to switch to an iFlow-supported model:

```
/model glm-5
```

Supported model IDs: `glm-5`, `deepseek-v3.2-chat`, `qwen3-coder-plus`, `kimi-k2-thinking`, `minimax-m2.5`, `kimi-k2.5`

> **Note**: If you don't switch models, Claude Code defaults to model names like `claude-sonnet-4-5-20250929`, which the proxy will automatically map to `glm-5`. You can also use the default model without manual switching.

**How It Works**: Claude Code sends Anthropic format requests to `/v1/messages` → iflow2api converts the request body to OpenAI format → forwards to iFlow API → converts the response back to Anthropic SSE format for Claude Code.

### Third-Party Clients

This service is compatible with the following OpenAI-compatible clients:

- **Claude Code**: Set `ANTHROPIC_BASE_URL=http://localhost:28000` (see guide above)
- **ChatGPT-Next-Web**: Set API address to `http://localhost:28000`
- **LobeChat**: Add OpenAI-compatible provider, set Base URL to `http://localhost:28000/v1`
- **Open WebUI**: Add OpenAI-compatible connection
- **Other OpenAI SDK compatible applications**

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Request                         │
│  (Claude Code / OpenAI SDK / curl / ChatGPT-Next-Web)      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    iflow2api Local Proxy                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  /v1/chat/completions │ /v1/messages │ /v1/models │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  1. Read ~/.iflow/settings.json for auth info       │   │
│  │  2. Add User-Agent: iFlow-Cli to unlock advanced    │   │
│  │     models                                          │   │
│  │  3. Forward request to iFlow API                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    iFlow API Service                        │
│                https://apis.iflow.cn/v1                     │
└─────────────────────────────────────────────────────────────┘
```

## How It Works

iFlow API distinguishes between regular API calls and CLI calls through the `User-Agent` header:

- **Regular API calls**: Only basic models available
- **CLI calls** (`User-Agent: iFlow-Cli`): Access to advanced models like GLM-5, DeepSeek, Kimi, etc.

This project adds the `User-Agent: iFlow-Cli` header to requests, allowing regular API clients to access CLI-exclusive models.

## Project Structure

```
iflow2api/
├── __init__.py          # Package initialization
├── __main__.py          # CLI entry point (python -m iflow2api)
├── main.py              # Main entry point
├── config.py            # iFlow configuration reader (from ~/.iflow/settings.json)
├── proxy.py             # API proxy (adds User-Agent header)
├── app.py               # FastAPI application (OpenAI-compatible endpoints)
├── oauth.py             # OAuth authentication logic
├── oauth_login.py       # OAuth login handler
├── token_refresher.py   # OAuth token auto-refresh
├── settings.py          # Application configuration management
├── gui.py               # GUI interface
├── vision.py            # Vision support (image input processing)
├── tray.py              # System tray
├── autostart.py         # Auto-start on boot
├── i18n.py              # Internationalization support
├── crypto.py            # Configuration encryption
├── ratelimit.py         # Rate limiting
├── instances.py         # Multi-instance management
├── server.py            # Server management
├── web_server.py        # Web server
├── updater.py           # Auto-update
└── admin/               # Web admin interface
    ├── auth.py          # Admin authentication
    ├── routes.py        # Admin routes
    ├── websocket.py     # WebSocket communication
    └── static/          # Static files (HTML/CSS/JS)
```

## FAQ

### Q: Prompted with "iFlow not logged in"

Ensure you have completed the login:

- **GUI method**: Click the "OAuth Login" button on the interface
- **CLI method**: Run the `iflow` command and complete the login

Check if the `~/.iflow/settings.json` file exists and contains the `apiKey` field.

### Q: Model call failed

1. Confirm the model ID is correct (refer to the model list above)
2. Check if your iFlow account has sufficient balance
3. Check the service logs for detailed error information

### Q: How to update the model list

The model list is hardcoded in `proxy.py` and sourced from iflow-cli source code. If iFlow updates supported models, you need to manually update this list.

### Q: Is iFlow CLI installation required?

No. Starting from v0.4.1, the project includes built-in GUI OAuth login functionality, so you can use it without installing iFlow CLI.

### Q: Can GUI login and CLI login configurations be shared?

Yes. Both login methods use the same configuration file `~/.iflow/settings.json`. After GUI login, command line mode can use it directly, and vice versa.

### Q: Downloaded app cannot execute on macOS

If you download `iflow2api.app` via browser on macOS and it cannot execute, there are usually two reasons:

1. **Missing execute permissions**: The executable file doesn't have execute bits
2. **Quarantine flag**: The file has `com.apple.quarantine` attribute

**Fix method**:

```bash
# Remove quarantine flag
xattr -cr iflow2api.app

# Add execute permission
chmod +x iflow2api.app/Contents/MacOS/iflow2api
```

After running the above commands, the application can run normally.

## License

MIT