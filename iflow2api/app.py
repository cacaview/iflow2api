"""FastAPI 应用 - OpenAI 兼容 API 服务 + Anthropic 兼容"""

import sys
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .config import load_iflow_config, check_iflow_login, IFlowConfig, save_iflow_config
from .proxy import IFlowProxy
from .token_refresher import OAuthTokenRefresher


# ============ Anthropic 格式转换函数 ============

def openai_to_anthropic_response(openai_response: dict, model: str) -> dict:
    """
    将 OpenAI 格式响应转换为 Anthropic 格式
    
    OpenAI 格式:
    {
      "id": "chatcmpl-xxx",
      "object": "chat.completion",
      "choices": [{"message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}],
      "usage": {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}
    }
    
    Anthropic 格式:
    {
      "id": "msg_xxx",
      "type": "message",
      "role": "assistant",
      "content": [{"type": "text", "text": "..."}],
      "model": "...",
      "stop_reason": "end_turn",
      "usage": {"input_tokens": N, "output_tokens": N}
    }
    """
    # 提取内容
    choices = openai_response.get("choices", [])
    content_text = ""
    finish_reason = "end_turn"
    
    if choices:
        choice = choices[0]
        message = choice.get("message", {})
        # 优先使用 content，如果没有则使用 reasoning_content
        content_text = message.get("content") or message.get("reasoning_content", "")
        
        # 转换 finish_reason
        openai_finish = choice.get("finish_reason", "stop")
        if openai_finish == "stop":
            finish_reason = "end_turn"
        elif openai_finish == "length":
            finish_reason = "max_tokens"
        elif openai_finish == "tool_calls":
            finish_reason = "tool_use"
        else:
            finish_reason = "end_turn"
    
    # 提取 usage
    openai_usage = openai_response.get("usage", {})
    
    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": content_text
            }
        ],
        "model": model,
        "stop_reason": finish_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": openai_usage.get("prompt_tokens", 0),
            "output_tokens": openai_usage.get("completion_tokens", 0),
        }
    }


def create_anthropic_stream_message_start(model: str) -> str:
    """创建 Anthropic 流式响应的 message_start 事件"""
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    data = {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}
        }
    }
    return f"event: message_start\ndata: {json.dumps(data)}\n\n"


def create_anthropic_content_block_start() -> str:
    """创建 Anthropic 流式响应的 content_block_start 事件"""
    data = {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""}
    }
    return f"event: content_block_start\ndata: {json.dumps(data)}\n\n"


def create_anthropic_content_block_delta(text: str) -> str:
    """创建 Anthropic 流式响应的 content_block_delta 事件"""
    data = {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": text}
    }
    return f"event: content_block_delta\ndata: {json.dumps(data)}\n\n"


def create_anthropic_content_block_stop() -> str:
    """创建 Anthropic 流式响应的 content_block_stop 事件"""
    data = {"type": "content_block_stop", "index": 0}
    return f"event: content_block_stop\ndata: {json.dumps(data)}\n\n"


def create_anthropic_message_delta(stop_reason: str = "end_turn", output_tokens: int = 0) -> str:
    """创建 Anthropic 流式响应的 message_delta 事件"""
    data = {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": output_tokens}
    }
    return f"event: message_delta\ndata: {json.dumps(data)}\n\n"


def create_anthropic_message_stop() -> str:
    """创建 Anthropic 流式响应的 message_stop 事件"""
    data = {"type": "message_stop"}
    return f"event: message_stop\ndata: {json.dumps(data)}\n\n"


def parse_openai_sse_chunk(line: str) -> Optional[dict]:
    """解析 OpenAI SSE 流式数据块"""
    line = line.strip()
    if not line or line == "data: [DONE]" or line == "data:[DONE]":
        return None
    # iFlow 使用 "data:" 没有空格，标准SSE使用 "data: "
    if line.startswith("data:"):
        data_str = line[5:].strip()  # 去掉 "data:" 前缀
        if not data_str or data_str == "[DONE]":
            return None
        try:
            return json.loads(data_str)
        except json.JSONDecodeError:
            return None
    return None


def extract_content_from_delta(delta: dict) -> str:
    """从 OpenAI delta 中提取内容（支持 content 和 reasoning_content）"""
    # 优先使用 content，然后尝试 reasoning_content
    content = delta.get("content", "")
    if not content:
        content = delta.get("reasoning_content", "")
    return content or ""


# ============ Anthropic → OpenAI 请求转换 ============

# Claude Code 发送的模型名 → iFlow 实际模型名映射
# 用户可通过 ANTHROPIC_MODEL 环境变量指定默认模型
DEFAULT_IFLOW_MODEL = "glm-5"


def get_mapped_model(anthropic_model: str) -> str:
    """
    将 Anthropic/Claude 模型名映射为 iFlow 模型名。
    如果是已知的 iFlow 模型则原样返回，否则回退到默认模型。
    """
    # iFlow 已知模型 ID
    known_iflow_models = {
        "glm-5", "iFlow-ROME-30BA3B", "deepseek-v3.2-chat",
        "qwen3-coder-plus", "kimi-k2-thinking", "minimax-m2.5", "kimi-k2.5",
    }
    if anthropic_model in known_iflow_models:
        return anthropic_model
    # Claude 系列模型名回退到默认
    print(f"[iflow2api] 模型映射: {anthropic_model} → {DEFAULT_IFLOW_MODEL}")
    return DEFAULT_IFLOW_MODEL


def anthropic_to_openai_request(body: dict) -> dict:
    """
    将 Anthropic Messages API 请求体转换为 OpenAI Chat Completions 格式。
    
    Anthropic 格式:
    {
      "model": "claude-sonnet-4-5-20250929",
      "max_tokens": 8096,
      "system": "You are...",           # 或 [{"type":"text","text":"..."}]
      "messages": [
        {"role": "user", "content": "hello"}  # content 可以是 str 或 [{"type":"text","text":"..."}]
      ],
      "stream": true
    }
    
    OpenAI 格式:
    {
      "model": "glm-5",
      "max_tokens": 8096,
      "messages": [
        {"role": "system", "content": "You are..."},
        {"role": "user", "content": "hello"}
      ],
      "stream": true
    }
    """
    openai_body = {}
    
    # 1. 模型映射
    openai_body["model"] = get_mapped_model(body.get("model", DEFAULT_IFLOW_MODEL))
    
    # 2. 构建 messages（先处理 system）
    messages = []
    system = body.get("system")
    if system:
        if isinstance(system, list):
            # Anthropic 格式: [{"type": "text", "text": "..."}]
            system_text = " ".join(
                block.get("text", "") for block in system if block.get("type") == "text"
            )
        else:
            system_text = str(system)
        if system_text:
            messages.append({"role": "system", "content": system_text})
    
    # 3. 转换 messages 中的 content
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        if isinstance(content, list):
            # Anthropic 内容块格式 → 提取纯文本
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        # 工具结果，提取内容
                        tool_content = block.get("content", "")
                        if isinstance(tool_content, list):
                            for tc in tool_content:
                                if isinstance(tc, dict) and tc.get("type") == "text":
                                    text_parts.append(tc.get("text", ""))
                        elif isinstance(tool_content, str):
                            text_parts.append(tool_content)
                elif isinstance(block, str):
                    text_parts.append(block)
            content = "\n".join(text_parts)
        
        messages.append({"role": role, "content": content})
    
    openai_body["messages"] = messages
    
    # 4. 透传兼容参数
    if "max_tokens" in body:
        openai_body["max_tokens"] = body["max_tokens"]
    if "temperature" in body:
        openai_body["temperature"] = body["temperature"]
    if "top_p" in body:
        openai_body["top_p"] = body["top_p"]
    if "stop_sequences" in body:
        openai_body["stop"] = body["stop_sequences"]
    if "stream" in body:
        openai_body["stream"] = body["stream"]
    
    return openai_body


# 全局代理实例
_proxy: Optional[IFlowProxy] = None
_config: Optional[IFlowConfig] = None
_refresher: Optional[OAuthTokenRefresher] = None


def get_proxy() -> IFlowProxy:
    """获取代理实例"""
    global _proxy, _config
    if _proxy is None:
        _config = load_iflow_config()
        _proxy = IFlowProxy(_config)
    return _proxy


def update_proxy_token(token_data: dict):
    """Token 刷新回调，同步更新内存中的代理配置并保存"""
    global _proxy, _config
    if _proxy and _config:
        print(f"[iflow2api] 检测到 Token 刷新，更新代理配置")
        _config.api_key = token_data["access_token"]
        _config.oauth_access_token = token_data["access_token"]
        
        # 更新其他 token 相关字段
        if "refresh_token" in token_data:
            _config.oauth_refresh_token = token_data["refresh_token"]
        if "expires_at" in token_data:
            _config.oauth_expires_at = token_data["expires_at"]
        
        # 保存到配置文件
        save_iflow_config(_config)
        print(f"[iflow2api] Token 已保存到配置文件")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global _refresher, _proxy
    # 启动时检查配置
    try:
        config = load_iflow_config()
        print(f"[iflow2api] 已加载 iFlow 配置")
        print(f"[iflow2api] API Base URL: {config.base_url}")
        print(f"[iflow2api] API Key: {config.api_key[:10]}...")
        if config.model_name:
            print(f"[iflow2api] 默认模型: {config.model_name}")
            
        # 启动 Token 刷新任务
        _refresher = OAuthTokenRefresher()
        _refresher.set_refresh_callback(update_proxy_token)
        _refresher.start()
        print(f"[iflow2api] 已启动 Token 自动刷新任务")
        
    except FileNotFoundError as e:
        print(f"[错误] {e}", file=sys.stderr)
        print("[提示] 请先运行 'iflow' 命令并完成登录", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    yield

    # 关闭时清理
    if _refresher:
        _refresher.stop()
        _refresher = None
        
    if _proxy:
        await _proxy.close()
        _proxy = None


# 创建 FastAPI 应用
app = FastAPI(
    title="iflow2api",
    description="将 iFlow CLI 的 AI 服务暴露为 OpenAI 兼容 API",
    version="0.1.0",
    lifespan=lifespan,
    redirect_slashes=True, # 自动处理末尾斜杠
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录请求信息"""
    print(f"[iflow2api] Request: {request.method} {request.url.path}")
    if request.method == "OPTIONS":
        # 显式处理 OPTIONS 请求以确保 CORS 正常
        response = await call_next(request)
        return response
    
    response = await call_next(request)
    print(f"[iflow2api] Response: {response.status_code}")
    
    # 如果返回 405，打印更多调试信息
    if response.status_code == 405:
        print(f"[调试] 路径 {request.url.path} 不支持 {request.method} 方法")
        print(f"[调试] 当前已注册的 POST 路由包括: /v1/chat/completions, /v1/messages, / 等")
        
    return response


# ============ 请求/响应模型 ============

class ChatMessage(BaseModel):
    role: str
    content: Any  # 可以是字符串或内容块列表


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False
    stop: Optional[list[str] | str] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    user: Optional[str] = None

    class Config:
        extra = "allow"  # 允许额外字段


# ============ API 端点 ============

@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "iflow2api",
        "version": "0.1.0",
        "description": "iFlow CLI AI 服务 → OpenAI 兼容 API",
        "endpoints": {
            "models": "/v1/models",
            "chat_completions": "/v1/chat/completions",
            "health": "/health",
        },
    }


@app.get("/health")
async def health():
    """健康检查"""
    is_logged_in = check_iflow_login()
    return {
        "status": "healthy" if is_logged_in else "degraded",
        "iflow_logged_in": is_logged_in,
    }


@app.get("/v1/models")
async def list_models():
    """获取可用模型列表"""
    try:
        proxy = get_proxy()
        return await proxy.get_models()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def create_error_response(status_code: int, message: str, error_type: str = "api_error") -> JSONResponse:
    """创建 OpenAI 兼容的错误响应"""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": None,
                "code": str(status_code)
            }
        }
    )


@app.post("/v1/chat/completions")
@app.post("/v1/chat/completions/")
@app.post("/chat/completions")
@app.post("/chat/completions/")
@app.post("/api/v1/chat/completions")
@app.post("/api/v1/chat/completions/")
async def chat_completions_openai(request: Request):
    """Chat Completions API - OpenAI 格式"""
    proxy = get_proxy()
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes.decode("utf-8"))
        stream = body.get("stream", False)

        if stream:
            # 获取流式迭代器
            try:
                # chat_completions 是 async def，返回一个 AsyncIterator
                stream_gen = await proxy.chat_completions(body, stream=True)
                
                async def generate():
                    try:
                        async for chunk in stream_gen:
                            yield chunk
                    except Exception as e:
                        # 传输过程中的错误
                        print(f"[iflow2api] Streaming error: {e}")
                
                return StreamingResponse(
                    generate(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )
            except Exception as e:
                error_msg = str(e)
                if hasattr(e, "response"):
                    try:
                        error_data = e.response.json()
                        error_msg = error_data.get("msg", error_msg)
                    except Exception:
                        pass
                return create_error_response(500, error_msg)
        else:
            result = await proxy.chat_completions(body, stream=False)
            return JSONResponse(content=result)

    except json.JSONDecodeError as e:
        return create_error_response(400, f"Invalid JSON: {e}", "invalid_request_error")
    except Exception as e:
        error_msg = str(e)
        status_code = 500
        if hasattr(e, "response"):
            try:
                status_code = e.response.status_code
                error_data = e.response.json()
                error_msg = error_data.get("msg", error_msg)
            except Exception:
                pass
        return create_error_response(status_code, error_msg)


@app.post("/v1/messages")
@app.post("/v1/messages/")
@app.post("/messages")
@app.post("/messages/")
@app.post("/api/v1/messages")
@app.post("/api/v1/messages/")
async def messages_anthropic(request: Request):
    """Messages API - Anthropic 格式（Claude Code 兼容）"""
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes.decode("utf-8"))
        stream = body.get("stream", False)
        original_model = body.get("model", "unknown")
        
        # 将 Anthropic 请求体转换为 OpenAI 格式
        openai_body = anthropic_to_openai_request(body)
        mapped_model = openai_body["model"]
        
        print(f"[iflow2api] Anthropic 格式请求: model={original_model} → {mapped_model}, stream={stream}")

        proxy = get_proxy()

        if stream:
            # 流式响应 - 转换为 Anthropic SSE 格式
            async def generate_anthropic_stream():
                # 发送 message_start
                yield create_anthropic_stream_message_start(mapped_model).encode('utf-8')
                # 发送 content_block_start
                yield create_anthropic_content_block_start().encode('utf-8')
                
                output_tokens = 0
                buffer = ""
                
                async for chunk in await proxy.chat_completions(openai_body, stream=True):
                    # OpenAI 流式数据是 bytes，需要解码
                    chunk_str = chunk.decode('utf-8') if isinstance(chunk, bytes) else chunk
                    buffer += chunk_str
                    
                    # 按行处理
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        parsed = parse_openai_sse_chunk(line)
                        if parsed:
                            choices = parsed.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = extract_content_from_delta(delta)
                                if content:
                                    output_tokens += len(content) // 4  # 粗略估计 token
                                    yield create_anthropic_content_block_delta(content).encode('utf-8')
                
                # 处理剩余 buffer
                for line in buffer.split("\n"):
                    if line.strip():
                        parsed = parse_openai_sse_chunk(line)
                        if parsed:
                            choices = parsed.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = extract_content_from_delta(delta)
                                if content:
                                    output_tokens += len(content) // 4
                                    yield create_anthropic_content_block_delta(content).encode('utf-8')
                
                # 发送结束事件
                yield create_anthropic_content_block_stop().encode('utf-8')
                yield create_anthropic_message_delta("end_turn", output_tokens).encode('utf-8')
                yield create_anthropic_message_stop().encode('utf-8')

            return StreamingResponse(
                generate_anthropic_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            # 非流式响应 - 转换为 Anthropic 格式
            openai_result = await proxy.chat_completions(openai_body, stream=False)
            anthropic_result = openai_to_anthropic_response(openai_result, mapped_model)
            print(f"[iflow2api] Anthropic 格式响应: id={anthropic_result['id']}")
            return JSONResponse(content=anthropic_result)

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, "response"):
            try:
                error_data = e.response.json()
                error_msg = error_data.get("msg", error_msg)
            except Exception:
                pass
        # Anthropic 格式的错误响应
        error_response = {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": error_msg
            }
        }
        return JSONResponse(content=error_response, status_code=500)


@app.post("/")
@app.post("/v1/")
async def root_post(request: Request):
    """根路径 POST - 尝试自动检测格式"""
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes.decode("utf-8"))
        
        # 简单启发式：如果请求中没有 choices 相关字段，默认使用 Anthropic 格式
        # 因为 CCR 主要使用 Anthropic 格式
        # 但为了安全起见，默认使用 OpenAI 格式
        stream = body.get("stream", False)
        model = body.get("model", "unknown")
        
        proxy = get_proxy()
        
        if stream:
            async def generate():
                async for chunk in await proxy.chat_completions(body, stream=True):
                    yield chunk
            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        else:
            result = await proxy.chat_completions(body, stream=False)
            return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/models")
async def list_models_compat():
    """Models API - 兼容不带 /v1 前缀的请求"""
    return await list_models()


def main():
    """主入口"""
    import uvicorn
    from .settings import load_settings

    # 检查是否已登录
    if not check_iflow_login():
        print("[错误] iFlow 未登录", file=sys.stderr)
        print("[提示] 请先运行 'iflow' 命令并完成登录", file=sys.stderr)
        sys.exit(1)

    # 加载配置
    settings = load_settings()

    print("=" * 50)
    print("  iflow2api - iFlow CLI AI 服务代理")
    print("=" * 50)
    print(f"  监听地址: {settings.host}:{settings.port}")
    print()

    # 启动服务 - 直接传入 app 对象而非字符串，避免打包后导入失败
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
