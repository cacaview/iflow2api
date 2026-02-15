# iflow2api

Exposes iFlow CLI's AI services as an OpenAI-compatible API.

## Features

- Automatically reads iFlow configuration file (`~/.iflow/settings.json`)
- Provides OpenAI-compatible API endpoints
- Supports both streaming and non-streaming responses
- Unlocks CLI-exclusive advanced models via `User-Agent: iFlow-Cli`
- Built-in GUI OAuth login interface - no need to install iFlow CLI
- Supports automatic OAuth token refresh

## Supported Models

| Model ID | Name | Description |
|----------|------|-------------|
| `glm-4.7` | GLM-4.7 | Zhipu GLM-4.7 (Recommended) |
| `iFlow-ROME-30BA3B` | iFlow-ROME-30BA3B | iFlow ROME 30B (Fast) |
| `deepseek-v3.2-chat` | DeepSeek-V3.2 | DeepSeek V3.2 Chat Model |
| `qwen3-coder-plus` | Qwen3-Coder-Plus | Tongyi Qianwen Qwen3 Coder Plus |
| `kimi-k2-thinking` | Kimi-K2-Thinking | Moonshot Kimi K2 Thinking Model |
| `minimax-m2.1` | MiniMax-M2.1 | MiniMax M2.1 |
| `kimi-k2-0905` | Kimi-K2-0905 | Moonshot Kimi K2 0905 |

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

The service runs by default on `http://localhost:8000`

### Custom Port

```bash
python -c "import uvicorn; from iflow2api.app import app; uvicorn.run(app, host='0.0.0.0', port=8001)"
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/v1/models` | GET | Get available model list |
| `/v1/chat/completions` | POST | Chat Completions API |
| `/models` | GET | Compatible endpoint (without /v1 prefix) |
| `/chat/completions` | POST | Compatible endpoint (without /v1 prefix) |

## Client Configuration Examples

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"  # API Key automatically read from iFlow configuration
)

# Non-streaming request
response = client.chat.completions.create(
    model="glm-4.7",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)

# Streaming request
stream = client.chat.completions.create(
    model="glm-4.7",
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
curl http://localhost:8000/v1/models

# Non-streaming request
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4.7",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# Streaming request
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4.7",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

### Third-Party Clients

This service is compatible with the following OpenAI-compatible clients:

- **ChatGPT-Next-Web**: Set API address to `http://localhost:8000`
- **LobeChat**: Add OpenAI-compatible provider, set Base URL to `http://localhost:8000/v1`
- **Open WebUI**: Add OpenAI-compatible connection
- **Other OpenAI SDK compatible applications**

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Request                         │
│  (OpenAI SDK / curl / ChatGPT-Next-Web / LobeChat)         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    iflow2api Local Proxy                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  /v1/chat/completions  │  /v1/models  │  /health   │   │
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
│                    iFlow API Service                         │
│                https://apis.iflow.cn/v1                      │
└─────────────────────────────────────────────────────────────┘
```

## How It Works

iFlow API distinguishes between regular API calls and CLI calls through the `User-Agent` header:

- **Regular API calls**: Only basic models available
- **CLI calls** (`User-Agent: iFlow-Cli`): Access to advanced models like GLM-4.7, DeepSeek, Kimi, etc.

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
└── gui.py               # GUI interface
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