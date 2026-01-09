"""FastAPI 应用 - OpenAI 兼容 API 服务"""

import sys
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .config import load_iflow_config, check_iflow_login, IFlowConfig
from .proxy import IFlowProxy


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
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
async def chat_completions(request: Request):
    """Chat Completions API - OpenAI 兼容"""
    try:
        # 解析请求体 - 使用 bytes 然后手动解码以处理编码问题
        body_bytes = await request.body()
        import json
        body = json.loads(body_bytes.decode("utf-8"))
        stream = body.get("stream", False)

        proxy = get_proxy()

        if stream:
            # 流式响应
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
            # 非流式响应
            result = await proxy.chat_completions(body, stream=False)
            return JSONResponse(content=result)

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    except Exception as e:
        error_msg = str(e)
        # 尝试解析 iFlow API 的错误响应
        if hasattr(e, "response"):
            try:
                error_data = e.response.json()
                error_msg = error_data.get("msg", error_msg)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=error_msg)


# ============ 兼容端点 ============

@app.post("/chat/completions")
async def chat_completions_compat(request: Request):
    """Chat Completions API - 兼容不带 /v1 前缀的请求"""
    return await chat_completions(request)


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

    # 启动服务
    uvicorn.run(
        "iflow2api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
