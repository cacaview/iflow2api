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

from .config import load_iflow_config, check_iflow_login, IFlowConfig
from .proxy import IFlowProxy


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


# 全局代理实例
_proxy: Optional[IFlowProxy] = None
_config: Optional[IFlowConfig] = None


def get_proxy() -> IFlowProxy:
    """获取代理实例"""
    global _proxy, _config
    if _proxy is None:
        _config = load_iflow_config()
        _proxy = IFlowProxy(_config)
    return _proxy


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时检查配置
    try:
        config = load_iflow_config()
        print(f"[iflow2api] 已加载 iFlow 配置")
        print(f"[iflow2api] API Base URL: {config.base_url}")
        print(f"[iflow2api] API Key: {config.api_key[:10]}...")
        if config.model_name:
            print(f"[iflow2api] 默认模型: {config.model_name}")
    except FileNotFoundError as e:
        print(f"[错误] {e}", file=sys.stderr)
        print("[提示] 请先运行 'iflow' 命令并完成登录", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    yield

    # 关闭时清理
    global _proxy
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


@app.post("/v1/chat/completions")
@app.post("/v1/chat/completions/")
@app.post("/chat/completions")
@app.post("/chat/completions/")
@app.post("/api/v1/chat/completions")
@app.post("/api/v1/chat/completions/")
async def chat_completions_openai(request: Request):
    """Chat Completions API - OpenAI 格式"""
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes.decode("utf-8"))
        stream = body.get("stream", False)

        proxy = get_proxy()

        if stream:
            async def generate():
                async for chunk in await proxy.chat_completions(body, stream=True):
                    yield chunk

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            result = await proxy.chat_completions(body, stream=False)
            return JSONResponse(content=result)

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
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/v1/messages")
@app.post("/v1/messages/")
@app.post("/messages")
@app.post("/messages/")
@app.post("/api/v1/messages")
@app.post("/api/v1/messages/")
async def messages_anthropic(request: Request):
    """Messages API - Anthropic 格式（CCR 兼容）"""
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes.decode("utf-8"))
        stream = body.get("stream", False)
        model = body.get("model", "unknown")
        
        print(f"[iflow2api] Anthropic 格式请求: model={model}, stream={stream}")

        proxy = get_proxy()

        if stream:
            # 流式响应 - 转换为 Anthropic SSE 格式
            async def generate_anthropic_stream():
                # 发送 message_start
                yield create_anthropic_stream_message_start(model).encode('utf-8')
                # 发送 content_block_start
                yield create_anthropic_content_block_start().encode('utf-8')
                
                output_tokens = 0
                buffer = ""
                
                async for chunk in await proxy.chat_completions(body, stream=True):
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
            openai_result = await proxy.chat_completions(body, stream=False)
            anthropic_result = openai_to_anthropic_response(openai_result, model)
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

    # 检查是否已登录
    if not check_iflow_login():
        print("[错误] iFlow 未登录", file=sys.stderr)
        print("[提示] 请先运行 'iflow' 命令并完成登录", file=sys.stderr)
        sys.exit(1)

    print("=" * 50)
    print("  iflow2api - iFlow CLI AI 服务代理")
    print("=" * 50)
    print()

    # 启动服务 - 直接传入 app 对象而非字符串，避免打包后导入失败
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
