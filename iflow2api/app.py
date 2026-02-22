"""FastAPI 应用 - OpenAI 兼容 API 服务 + Anthropic 兼容"""

import sys
import json
import logging
import uuid
import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("iflow2api")

from .config import load_iflow_config, check_iflow_login, IFlowConfig, save_iflow_config
from .proxy import IFlowProxy
from .token_refresher import OAuthTokenRefresher
from .vision import (
    is_vision_model,
    supports_vision,
    get_vision_model_info,
    detect_image_content,
    process_message_content,
    get_vision_models_list,
    get_max_images,
    DEFAULT_VISION_MODEL,
)
from .version import get_version, get_startup_info, get_diagnostic_info, is_docker


# ============ Anthropic 格式转换函数 ============

def openai_to_anthropic_response(openai_response: dict, model: str) -> dict:
    """
    将 OpenAI 格式响应转换为 Anthropic 格式
    
    OpenAI 格式:
    {
      "id": "chatcmpl-xxx",
      "object": "chat.completion",
      "choices": [{"message": {"role": "assistant", "content": "...", "tool_calls": [...]}, "finish_reason": "stop"}],
      "usage": {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}
    }
    
    Anthropic 格式:
    {
      "id": "msg_xxx",
      "type": "message",
      "role": "assistant",
      "content": [{"type": "text", "text": "..."}, {"type": "tool_use", "id": "...", "name": "...", "input": {...}}],
      "model": "...",
      "stop_reason": "end_turn" | "tool_use",
      "usage": {"input_tokens": N, "output_tokens": N}
    }
    """
    choices = openai_response.get("choices", [])
    content_blocks = []
    finish_reason = "end_turn"

    if not choices:
        logger.warning("OpenAI 响应中 choices 数组为空")
        logger.debug("完整响应: %s", json.dumps(openai_response, ensure_ascii=False)[:500])
        content_blocks = [{"type": "text", "text": "[错误: API 未返回有效内容]"}]
    else:
        choice = choices[0]
        message = choice.get("message", {})
        content_text = message.get("content") or message.get("reasoning_content", "")
        tool_calls = message.get("tool_calls") or []

        # 添加文本内容块
        if content_text:
            content_blocks.append({"type": "text", "text": content_text})

        # 将 OpenAI tool_calls 转换为 Anthropic tool_use 内容块
        for tc in tool_calls:
            func = tc.get("function", {})
            try:
                tool_input = json.loads(func.get("arguments", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                tool_input = {"_raw": func.get("arguments", "")}
            content_blocks.append({
                "type": "tool_use",
                "id": tc.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                "name": func.get("name", ""),
                "input": tool_input,
            })

        if not content_blocks:
            logger.warning("message.content 和 tool_calls 均为空: %s", json.dumps(message, ensure_ascii=False))
            content_blocks = [{"type": "text", "text": "[错误: API 返回空内容]"}]

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
        "content": content_blocks,
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


def create_anthropic_content_block_start(index: int = 0, block_type: str = "text") -> str:
    """创建 Anthropic 流式响应的 content_block_start 事件
    
    Args:
        index: 内容块索引
        block_type: 内容块类型 ("text" 或 "thinking")
    """
    if block_type == "thinking":
        content_block = {"type": "thinking", "thinking": ""}
    else:
        content_block = {"type": "text", "text": ""}
    data = {
        "type": "content_block_start",
        "index": index,
        "content_block": content_block
    }
    return f"event: content_block_start\ndata: {json.dumps(data)}\n\n"


def create_anthropic_content_block_delta(text: str, index: int = 0, delta_type: str = "text_delta") -> str:
    """创建 Anthropic 流式响应的 content_block_delta 事件
    
    Args:
        text: 内容文本
        index: 内容块索引
        delta_type: delta 类型 ("text_delta" 或 "thinking_delta")
    """
    if delta_type == "thinking_delta":
        delta = {"type": "thinking_delta", "thinking": text}
    else:
        delta = {"type": "text_delta", "text": text}
    data = {
        "type": "content_block_delta",
        "index": index,
        "delta": delta
    }
    return f"event: content_block_delta\ndata: {json.dumps(data)}\n\n"


def create_anthropic_content_block_stop(index: int = 0) -> str:
    """创建 Anthropic 流式响应的 content_block_stop 事件
    
    Args:
        index: 内容块索引
    """
    data = {"type": "content_block_stop", "index": index}
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


def create_anthropic_tool_use_block_start(index: int, tool_use_id: str, name: str) -> str:
    """创建 Anthropic 流式响应的 tool_use content_block_start 事件"""
    data = {
        "type": "content_block_start",
        "index": index,
        "content_block": {"type": "tool_use", "id": tool_use_id, "name": name, "input": {}}
    }
    return f"event: content_block_start\ndata: {json.dumps(data)}\n\n"


def create_anthropic_input_json_delta(partial_json: str, index: int) -> str:
    """创建 Anthropic 流式响应的 input_json_delta content_block_delta 事件"""
    data = {
        "type": "content_block_delta",
        "index": index,
        "delta": {"type": "input_json_delta", "partial_json": partial_json}
    }
    return f"event: content_block_delta\ndata: {json.dumps(data)}\n\n"


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


def extract_content_from_delta(delta: dict, preserve_reasoning: bool = False) -> tuple[str, str]:
    """从 OpenAI delta 中提取内容
    
    Args:
        delta: OpenAI 流式响应的 delta 对象
        preserve_reasoning: 是否区分思考内容和回答内容
            - False（默认）: 将 reasoning_content 也作为普通文本输出（兼容模式）
            - True: 区分思考内容和回答内容，返回 (内容, 类型) 元组
    
    Returns:
        (内容, 类型) 元组，类型为 "text"、"thinking" 或 ""
    
    上游API行为（GLM-5）：
    - 流式响应：思考过程和回答分开返回
      - 大部分chunk只有 reasoning_content（思考过程）
      - 少部分chunk只有 content（最终回答）
      - 两者不会同时出现在同一个chunk中
    """
    content = delta.get("content", "")
    reasoning_content = delta.get("reasoning_content", "")
    
    if content:
        # 有 content，直接返回（这是最终回答）
        return (content, "text")
    elif reasoning_content:
        if preserve_reasoning:
            # 区分思考内容，标记为 thinking 类型
            return (reasoning_content, "thinking")
        else:
            # 兼容模式，将思考内容作为普通文本输出
            return (reasoning_content, "text")
    else:
        # 两者都为空
        return ("", "")


# ============ Anthropic → OpenAI 请求转换 ============

# Claude Code 发送的模型名 → iFlow 实际模型名映射
# 用户可通过 ANTHROPIC_MODEL 环境变量指定默认模型
DEFAULT_IFLOW_MODEL = "glm-5"


def get_mapped_model(anthropic_model: str, has_images: bool = False) -> str:
    """
    将 Anthropic/Claude 模型名映射为 iFlow 模型名。
    如果是已知的 iFlow 模型则原样返回，否则回退到默认模型。
    
    注意：所有模型都支持图像输入，由上游 API 决定如何处理。
    
    Args:
        anthropic_model: 原始模型名
        has_images: 请求是否包含图像（保留参数，用于日志）
    
    Returns:
        映射后的模型名
    """
    # iFlow 已知模型 ID（与 proxy.py get_models() 保持一致）
    known_iflow_models = {
        # 文本模型
        "glm-4.6", "glm-4.7", "glm-5",
        "iFlow-ROME-30BA3B", "deepseek-v3.2-chat",
        "qwen3-coder-plus", "kimi-k2", "kimi-k2-thinking", "kimi-k2.5",
        "kimi-k2-0905",  # L-02 修复：补充缺失模型
        "minimax-m2.5",
        # 视觉模型
        "glm-4v", "glm-4v-plus", "glm-4v-flash", "glm-4.5v", "glm-4.6v",
        "moonshot-v1-8k-vision", "moonshot-v1-32k-vision", "moonshot-v1-128k-vision",
        "qwen-vl-plus", "qwen-vl-max", "qwen2.5-vl", "qwen3-vl",
    }
    
    if anthropic_model in known_iflow_models:
        return anthropic_model
    
    # Claude 系列模型名回退到默认模型
    logger.info("模型映射: %s → %s", anthropic_model, DEFAULT_IFLOW_MODEL)
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
    
    支持图像输入（Vision）:
    - Anthropic 格式: {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
    - OpenAI 格式: {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    """
    openai_body = {}
    
    # 检测是否有图像内容
    has_images = False
    for msg in body.get("messages", []):
        content = msg.get("content", "")
        images = detect_image_content(content)
        if images:
            has_images = True
            break
    
    # 1. 模型映射（考虑图像支持）
    openai_body["model"] = get_mapped_model(body.get("model", DEFAULT_IFLOW_MODEL), has_images)
    
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
    
    # 3. 转换 messages 中的 content（支持图像、工具调用）
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            if role == "assistant":
                # 提取文本块和 tool_use 块
                tool_use_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                text_parts = [
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ] + [b for b in content if isinstance(b, str)]

                openai_msg: dict = {"role": "assistant"}
                text_content = "\n".join(text_parts)
                openai_msg["content"] = text_content if text_content else None

                if tool_use_blocks:
                    openai_msg["tool_calls"] = [
                        {
                            "id": b.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                            "type": "function",
                            "function": {
                                "name": b.get("name", ""),
                                "arguments": json.dumps(b.get("input", {}), ensure_ascii=False),
                            },
                        }
                        for b in tool_use_blocks
                    ]
                messages.append(openai_msg)

            else:  # role == "user"
                # 先处理 tool_result 块 → 转成 role=tool 消息
                tool_result_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                for tr in tool_result_blocks:
                    tr_content = tr.get("content", "")
                    if isinstance(tr_content, list):
                        tr_text = "\n".join(
                            tc.get("text", "") for tc in tr_content
                            if isinstance(tc, dict) and tc.get("type") == "text"
                        )
                    else:
                        tr_text = str(tr_content) if tr_content else ""
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "content": tr_text,
                    })

                # 处理剩余内容（文本 / 图像）
                remaining = [b for b in content if not (isinstance(b, dict) and b.get("type") == "tool_result")]
                if remaining:
                    images = detect_image_content(remaining)
                    if images:
                        # 有图像，使用 OpenAI 多模态格式
                        text_parts = [
                            b.get("text", "") for b in remaining
                            if isinstance(b, dict) and b.get("type") == "text"
                        ] + [b for b in remaining if isinstance(b, str)]
                        multimodal_content = []
                        combined_text = "\n".join(text_parts)
                        if combined_text.strip():
                            multimodal_content.append({"type": "text", "text": combined_text})
                        from .vision import convert_to_openai_format
                        multimodal_content.extend(convert_to_openai_format(images))
                        messages.append({"role": "user", "content": multimodal_content})
                    else:
                        # 无图像，提取纯文本
                        text_parts = [
                            b.get("text", "") for b in remaining
                            if isinstance(b, dict) and b.get("type") == "text"
                        ] + [b for b in remaining if isinstance(b, str)]
                        combined = "\n".join(text_parts)
                        if combined or not tool_result_blocks:
                            messages.append({"role": "user", "content": combined})
                # 如果只有 tool_result 没有额外文本/图像，则不追加 user 消息
        else:
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

    # 5. 转换 tools（Anthropic input_schema → OpenAI parameters）
    if "tools" in body:
        openai_body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            }
            for t in body["tools"]
        ]

    # 6. 转换 tool_choice
    if "tool_choice" in body:
        tc = body["tool_choice"]
        if isinstance(tc, dict):
            tc_type = tc.get("type", "auto")
            if tc_type == "auto":
                openai_body["tool_choice"] = "auto"
            elif tc_type == "any":
                openai_body["tool_choice"] = "required"
            elif tc_type == "tool":
                openai_body["tool_choice"] = {
                    "type": "function",
                    "function": {"name": tc.get("name", "")},
                }
            else:
                openai_body["tool_choice"] = "auto"
        elif isinstance(tc, str):
            openai_body["tool_choice"] = tc

    return openai_body


# 全局代理实例
_proxy: Optional[IFlowProxy] = None
_config: Optional[IFlowConfig] = None
_refresher: Optional[OAuthTokenRefresher] = None

# 上游 API 并发信号量 - 在 lifespan 中根据配置初始化
_api_request_lock: Optional[asyncio.Semaphore] = None


class IFlowNotConfiguredError(Exception):
    """iFlow 未配置异常"""
    pass


def get_proxy() -> IFlowProxy:
    """获取代理实例
    
    如果 iFlow 配置不存在，抛出 IFlowNotConfiguredError 异常。
    """
    global _proxy, _config
    if _proxy is None:
        try:
            _config = load_iflow_config()
            _proxy = IFlowProxy(_config)
        except (FileNotFoundError, ValueError) as e:
            raise IFlowNotConfiguredError(
                "iFlow 未配置，请通过 WebUI 完成登录: http://localhost:28000/admin"
            ) from e
    return _proxy


def update_proxy_token(token_data: dict):
    """Token 刷新回调，同步更新内存中的代理配置并保存"""
    global _proxy, _config
    if _proxy and _config:
        logger.info("检测到 Token 刷新，更新代理配置")
        _config.api_key = token_data["access_token"]
        _config.oauth_access_token = token_data["access_token"]
        
        # 更新其他 token 相关字段
        if "refresh_token" in token_data:
            _config.oauth_refresh_token = token_data["refresh_token"]
        if "expires_at" in token_data:
            _config.oauth_expires_at = token_data["expires_at"]
        
        # 保存到配置文件
        save_iflow_config(_config)
        logger.info("Token 已保存到配置文件")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理
    
    支持无配置启动：如果 iFlow 配置不存在，服务仍可启动，
    用户可通过 WebUI OAuth 登录完成配置。
    """
    global _refresher, _proxy, _api_request_lock, _config
    # 启动时打印版本和系统信息
    logger.info("%s", get_startup_info())
    
    # 初始化并发信号量（无论是否有配置都需要）
    from .settings import load_settings
    settings = load_settings()
    _api_request_lock = asyncio.Semaphore(settings.api_concurrency)
    logger.info("上游 API 并发数: %d", settings.api_concurrency)
    if settings.api_concurrency > 1:
        logger.warning("警告: 并发数 > 1 可能导致上游 API 返回 429 限流错误，建议保持默认值 1")
    
    # 尝试加载 iFlow 配置（可选）
    # 优先检查应用主配置 ~/.iflow2api/config.json（用户通过 WebUI 登录后保存）
    # 其次检查 iFlow CLI 配置 ~/.iflow/settings.json
    from pathlib import Path
    app_config_path = Path.home() / ".iflow2api" / "config.json"
    app_config_exists = app_config_path.exists()
    
    try:
        config = load_iflow_config()
        _config = config
        logger.info("已加载 iFlow 配置")
        logger.info("API Base URL: %s", config.base_url)
        logger.info("API Key: ****%s (masked)", config.api_key[-4:])
        if config.model_name:
            logger.info("默认模型: %s", config.model_name)
            
        # 启动 Token 刷新任务
        _refresher = OAuthTokenRefresher()
        _refresher.set_refresh_callback(update_proxy_token)
        _refresher.start()
        logger.info("已启动 Token 自动刷新任务")
        
    except FileNotFoundError:
        # 检查是否存在应用主配置（用户通过 WebUI 登录）
        if app_config_exists:
            logger.info("检测到应用配置文件，等待 WebUI 初始化...")
            logger.info("访问 http://localhost:%d/admin 进入管理界面", settings.port)
        else:
            logger.warning("iFlow 配置文件不存在，请通过 WebUI 完成登录")
            logger.warning("访问 http://localhost:%d/admin 进入管理界面", settings.port)
    except ValueError as e:
        logger.warning("iFlow 配置文件格式错误: %s", e)
        logger.warning("请通过 WebUI 重新登录")

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
    description="""
## iflow2api - iFlow CLI AI 服务代理

将 iFlow CLI 的 AI 服务暴露为 OpenAI 兼容 API，支持多种 AI 模型。

### 功能特性

- **OpenAI 兼容 API**: 支持 `/v1/chat/completions` 端点
- **Anthropic 兼容 API**: 支持 `/v1/messages` 端点（Claude Code 兼容）
- **多模型支持**: GLM-4.6/4.7/5、DeepSeek-V3.2、Qwen3-Coder-Plus、Kimi-K2/K2.5、MiniMax-M2.5
- **流式响应**: 支持 SSE 流式输出
- **OAuth 认证**: 支持 iFlow OAuth 登录

### 支持的模型

| 模型 ID | 名称 | 说明 |
|---------|------|------|
| `glm-4.6` | GLM-4.6 | 智谱 GLM-4.6 |
| `glm-4.7` | GLM-4.7 | 智谱 GLM-4.7 |
| `glm-5` | GLM-5 | 智谱 GLM-5 (推荐) |
| `deepseek-v3.2-chat` | DeepSeek-V3.2 | DeepSeek V3.2 对话模型 |
| `qwen3-coder-plus` | Qwen3-Coder-Plus | 通义千问 Qwen3 Coder |
| `kimi-k2` | Kimi-K2 | Moonshot Kimi K2 |
| `kimi-k2.5` | Kimi-K2.5 | Moonshot Kimi K2.5 |
| `minimax-m2.5` | MiniMax-M2.5 | MiniMax M2.5 |

### 使用方式

1. 确保已安装并登录 iFlow CLI: `npm install -g @iflow-ai/iflow-cli && iflow login`
2. 启动服务: `iflow2api` 或通过 GUI 启动
3. 配置客户端使用 `http://localhost:28000/v1` 作为 API 端点
""",
version=get_version(),
lifespan=lifespan,
    redirect_slashes=True,  # 自动处理末尾斜杠
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc
    openapi_url="/openapi.json",  # OpenAPI schema
)

# 添加 CORS 中间件（H-05 修复：不再同时使用通配符 origin + credentials）
# 默认允许所有来源但不携带凭据；如需限制来源请在此列举
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # RFC 禁止 allow_origins=["*"] + allow_credentials=True
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ 请求体大小限制中间件 ============

_MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024  # 10 MB（H-07 修复）

@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    """拒绝超大请求体，防止内存耗尽 DoS（H-07 修复）"""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_REQUEST_BODY_SIZE:
        return JSONResponse(
            status_code=413,
            content={"error": {"message": "Request body too large", "type": "invalid_request_error"}},
        )
    return await call_next(request)


# ============ 自定义 API 鉴权中间件 ============

# 简单内存缓存，减少每次请求读磁盘（H-08 修复）
_settings_cache: dict = {"data": None, "ts": 0.0}
_SETTINGS_CACHE_TTL = 5.0  # 5 秒内复用缓存


def _get_cached_settings():
    """获取缓存的设置，超过 TTL 才重新读盘"""
    import time as _time
    from .settings import load_settings
    now = _time.monotonic()
    if _settings_cache["data"] is None or now - _settings_cache["ts"] > _SETTINGS_CACHE_TTL:
        _settings_cache["data"] = load_settings()
        _settings_cache["ts"] = now
    return _settings_cache["data"]


@app.middleware("http")
async def custom_auth_middleware(request: Request, call_next):
    """自定义 API 鉴权中间件

    如果配置了 custom_api_key，则验证请求头中的授权信息
    支持 "Bearer {key}" 和 "{key}" 两种格式
    """
    # 跳过健康检查、文档等路由
    skip_paths = ["/health", "/docs", "/redoc", "/openapi.json", "/admin"]
    if any(request.url.path.startswith(path) for path in skip_paths):
        return await call_next(request)

    # 使用缓存的设置，避免每次请求读磁盘（H-08 修复）
    settings = _get_cached_settings()
    
    # 如果未设置 custom_api_key，则跳过验证
    if not settings.custom_api_key:
        return await call_next(request)
    
    # 获取授权标头
    auth_header_name = settings.custom_auth_header or "Authorization"
    auth_value = request.headers.get(auth_header_name)
    
    # 验证授权信息
    if not auth_value:
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "message": f"Missing {auth_header_name} header",
                    "type": "authentication_error",
                    "code": "missing_api_key",
                }
            },
        )
    
    # 提取实际的 key（支持 "Bearer {key}" 和 "{key}" 格式）
    actual_key = auth_value
    if auth_value.startswith("Bearer "):
        actual_key = auth_value[7:]  # 移除 "Bearer " 前缀
    
    # 验证 key（使用常数时间比较防止时序攻击）
    import hmac as _hmac
    if not _hmac.compare_digest(actual_key, settings.custom_api_key):
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "message": "Invalid API key",
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                }
            },
        )
    
    # 验证通过，继续处理请求
    return await call_next(request)


# ============ 管理界面 ============

# 挂载静态文件目录
import os as _os
_admin_static_dir = _os.path.join(_os.path.dirname(__file__), "admin", "static")
if _os.path.exists(_admin_static_dir):
    app.mount("/admin/static", StaticFiles(directory=_admin_static_dir), name="admin_static")


@app.get("/admin", response_class=HTMLResponse, tags=["Admin"])
@app.get("/admin/", response_class=HTMLResponse, tags=["Admin"])
async def admin_page():
    """管理界面入口"""
    index_path = _os.path.join(_admin_static_dir, "index.html")
    if _os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse(content="<h1>管理界面未找到</h1>", status_code=404)


# 注册管理界面路由
try:
    from .admin.routes import admin_router, set_server_manager
    app.include_router(admin_router)
except ImportError as e:
    logger.warning("无法加载管理界面路由: %s", e)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录请求信息，包括请求体大小和响应时间"""
    start_time = time.time()
    
    # 获取请求体大小（仅对 POST/PUT/PATCH 请求）
    body_size = 0
    if request.method in ("POST", "PUT", "PATCH"):
        content_length = request.headers.get("content-length")
        if content_length:
            body_size = int(content_length)
    
    # 格式化请求体大小
    def format_size(size: int) -> str:
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size/1024:.1f}KB"
        else:
            return f"{size/1024/1024:.1f}MB"
    
    logger.info("Request: %s %s%s", request.method, request.url.path,
                 f" ({format_size(body_size)})" if body_size > 0 else "")
    
    if request.method == "OPTIONS":
        # 显式处理 OPTIONS 请求以确保 CORS 正常
        response = await call_next(request)
        return response
    
    response = await call_next(request)
    
    # 计算响应时间
    elapsed_ms = (time.time() - start_time) * 1000
    logger.info("Response: %d (%.0fms)", response.status_code, elapsed_ms)
    
    # 如果返回 405，打印更多调试信息
    if response.status_code == 405:
        logger.debug("路径 %s 不支持 %s 方法", request.url.path, request.method)
        logger.debug("当前已注册的 POST 路由包括: /v1/chat/completions, /v1/messages, / 等")
        
    return response


# ============ 请求/响应模型 ============

class ChatMessage(BaseModel):
    """聊天消息"""
    role: str
    content: Any  # 可以是字符串或内容块列表


class ChatCompletionRequest(BaseModel):
    """Chat Completions API 请求体"""
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

    model_config = ConfigDict(extra="allow")


# ============ 示例请求 ============

OPENAI_CHAT_EXAMPLE = {
    "model": "glm-5",
    "messages": [
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "user", "content": "你好，请介绍一下你自己。"}
    ],
    "temperature": 0.7,
    "max_tokens": 1024,
    "stream": False
}

OPENAI_CHAT_STREAM_EXAMPLE = {
    "model": "glm-5",
    "messages": [
        {"role": "user", "content": "写一首关于春天的诗。"}
    ],
    "stream": True
}

ANTHROPIC_MESSAGES_EXAMPLE = {
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 1024,
    "system": "你是一个有帮助的助手。",
    "messages": [
        {"role": "user", "content": "你好，请介绍一下你自己。"}
    ]
}


# ============ API 端点 ============

@app.get(
    "/",
    summary="根路径",
    description="返回服务基本信息和可用端点列表",
    response_description="服务信息",
    tags=["基本信息"],
)
async def root():
    """根路径"""
    return {
        "service": "iflow2api",
        "version": get_version(),
        "description": "iFlow CLI AI 服务 → OpenAI 兼容 API",
        "endpoints": {
            "models": "/v1/models",
            "chat_completions": "/v1/chat/completions",
            "messages": "/v1/messages",
            "health": "/health",
            "docs": "/docs",
            "redoc": "/redoc",
        },
    }


@app.get(
    "/health",
    summary="健康检查",
    description="检查服务健康状态和 iFlow 登录状态",
    response_description="健康状态",
    tags=["基本信息"],
)
async def health():
    """健康检查"""
    is_logged_in = check_iflow_login()
    diagnostic = get_diagnostic_info()
    return {
        "status": "healthy" if is_logged_in else "degraded",
        "iflow_logged_in": is_logged_in,
        "version": diagnostic["version"],
        "os": diagnostic["os"],
        "platform": diagnostic["platform"]["system"],
        "architecture": diagnostic["platform"]["architecture"],
        "python": diagnostic["platform"]["python_version"],
        "runtime": diagnostic["runtime"],
        "docker": diagnostic["docker"],
        "kubernetes": diagnostic["kubernetes"],
        "wsl": diagnostic["wsl"],
    }


@app.get(
    "/v1/models",
    summary="获取模型列表",
    description="获取所有可用的 AI 模型列表",
    response_description="模型列表",
    tags=["模型"],
)
async def list_models():
    """获取可用模型列表"""
    try:
        proxy = get_proxy()
        return await proxy.get_models()
    except IFlowNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/v1/vision-models",
    summary="获取视觉模型列表",
    description="获取所有支持图像输入的视觉模型列表",
    response_description="视觉模型列表",
    tags=["模型"],
)
async def list_vision_models():
    """获取支持视觉功能的模型列表"""
    vision_models = get_vision_models_list()
    return {
        "object": "list",
        "data": [
            {
                "id": model["id"],
                "object": "model",
                "owned_by": model["provider"],
                "supports_vision": True,
                "max_images": model["max_images"],
            }
            for model in vision_models
        ],
    }


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


@app.post(
    "/v1/chat/completions",
    summary="Chat Completions API (OpenAI 格式)",
    description="""
OpenAI 兼容的 Chat Completions API 端点。

支持流式和非流式响应。使用 `stream: true` 启用流式输出。

**支持的模型**: glm-4.6, glm-4.7, glm-5, deepseek-v3.2-chat, qwen3-coder-plus, kimi-k2, kimi-k2.5, minimax-m2.5
""",
    response_description="Chat completion 响应",
    tags=["Chat"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["model", "messages"],
                        "properties": {
                            "model": {
                                "type": "string",
                                "description": "模型 ID",
                                "example": "glm-5",
                            },
                            "messages": {
                                "type": "array",
                                "description": "对话消息列表",
                                "items": {
                                    "type": "object",
                                    "required": ["role", "content"],
                                    "properties": {
                                        "role": {
                                            "type": "string",
                                            "enum": ["system", "user", "assistant"],
                                            "description": "消息角色",
                                        },
                                        "content": {
                                            "type": "string",
                                            "description": "消息内容",
                                        },
                                    },
                                },
                            },
                            "temperature": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 2,
                                "description": "采样温度",
                            },
                            "top_p": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                                "description": "核采样参数",
                            },
                            "max_tokens": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "最大生成 token 数",
                            },
                            "stream": {
                                "type": "boolean",
                                "description": "是否启用流式输出",
                                "default": False,
                            },
                            "stop": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ],
                                "description": "停止序列",
                            },
                        },
                    },
                    "examples": {
                        "basic": {
                            "summary": "基本对话",
                            "value": OPENAI_CHAT_EXAMPLE,
                        },
                        "streaming": {
                            "summary": "流式输出",
                            "value": OPENAI_CHAT_STREAM_EXAMPLE,
                        },
                    },
                }
            },
        }
    },
)
@app.post("/v1/chat/completions/")
@app.post("/chat/completions")
@app.post("/chat/completions/")
@app.post("/api/v1/chat/completions")
@app.post("/api/v1/chat/completions/")
async def chat_completions_openai(request: Request):
    """Chat Completions API - OpenAI 格式"""
    try:
        proxy = get_proxy()
    except IFlowNotConfiguredError as e:
        return create_error_response(503, str(e), "iflow_not_configured")
    
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes.decode("utf-8"))
        if "messages" not in body:
            return create_error_response(422, "Field 'messages' is required", "invalid_request_error")
        stream = body.get("stream", False)
        model = body.get("model", "unknown")
        msg_count = len(body.get("messages", []))
        has_tools = "tools" in body
        logger.info("Chat请求: model=%s, stream=%s, messages=%d, has_tools=%s",
                     model, stream, msg_count, has_tools)

        if stream:
            # 流式响应 - 整个流式传输过程都在锁内进行
            try:
                async def generate_with_lock():
                    """在锁内完成整个流式传输"""
                    async with _api_request_lock:
                        logger.debug("获取上游流式响应...")
                        stream_gen = await proxy.chat_completions(body, stream=True)
                        chunk_count = 0
                        try:
                            async for chunk in stream_gen:
                                chunk_count += 1
                                if chunk_count <= 3:
                                    logger.debug("流式chunk[%d]: %s", chunk_count, chunk[:200])
                                yield chunk
                        except Exception as e:
                            # 传输过程中的错误
                            logger.error("Streaming error after %d chunks: %s", chunk_count, e)
                        else:
                            # 正常结束：确保发送 [DONE] 标记（上游不一定发送）
                            if chunk_count > 0:
                                yield b"data: [DONE]\n\n"
                        finally:
                            logger.debug("流式完成: 共 %d chunks", chunk_count)
                            if chunk_count == 0:
                                # 上游返回了空的流式响应，生成一个错误回退
                                logger.warning("生成错误回退响应 (0 chunks from upstream)")
                                import time as _time
                                fallback = {
                                    "id": f"fallback-{int(_time.time())}",
                                    "object": "chat.completion.chunk",
                                    "created": int(_time.time()),
                                    "model": model,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"role": "assistant", "content": "上游api返回空信息，可能是上下文超限了"},
                                        "finish_reason": "stop"
                                    }]
                                }
                                yield ("data: " + json.dumps(fallback, ensure_ascii=False) + "\n\n").encode("utf-8")
                                yield b"data: [DONE]\n\n"
                
                return StreamingResponse(
                    generate_with_lock(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )
            except Exception as e:
                error_msg = str(e)
                resp = getattr(e, "response", None)
                if resp is not None:
                    try:
                        error_data = resp.json()
                        error_msg = error_data.get("msg", error_msg)
                    except Exception:
                        pass
                return create_error_response(500, error_msg)
        else:
            # 使用锁确保同一时间只有一个上游请求
            async with _api_request_lock:
                logger.debug("获取上游非流式响应...")
                result = await proxy.chat_completions(body, stream=False)
            # 验证响应包含有效的 choices
            if not result.get("choices"):
                logger.error("API 响应缺少 choices 数组: %s", json.dumps(result, ensure_ascii=False)[:500])
                return create_error_response(500, "API 响应格式错误: 缺少 choices 数组")
            
            # 日志输出关键信息
            msg = result["choices"][0].get("message", {})
            content = msg.get("content")
            reasoning = msg.get("reasoning_content")
            tool_calls = msg.get("tool_calls")
            logger.debug("非流式响应: content=%r, reasoning=%s, tool_calls=%s",
                         content[:80] if content else None,
                         '有' if reasoning else '无',
                         '有' if tool_calls else '无')
            
            return JSONResponse(content=result)

    except json.JSONDecodeError as e:
        return create_error_response(400, f"Invalid JSON: {e}", "invalid_request_error")
    except Exception as e:
        error_msg = str(e)
        status_code = 500
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                status_code = resp.status_code
                error_data = resp.json()
                error_msg = error_data.get("msg", error_msg)
            except Exception:
                pass
        return create_error_response(status_code, error_msg)


@app.post(
    "/v1/messages",
    summary="Messages API (Anthropic 格式)",
    description="""
Anthropic 兼容的 Messages API 端点，支持 Claude Code 等客户端。

请求格式与 Anthropic API 兼容，会自动转换为 OpenAI 格式并映射到 iFlow 模型。

**模型映射**: Claude 系列模型会自动映射到 glm-5，也可直接指定 iFlow 模型 ID。
""",
    response_description="Messages 响应",
    tags=["Chat"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["model", "max_tokens", "messages"],
                        "properties": {
                            "model": {
                                "type": "string",
                                "description": "模型 ID (Claude 系列会自动映射到 glm-5)",
                                "example": "claude-sonnet-4-5-20250929",
                            },
                            "max_tokens": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "最大生成 token 数",
                            },
                            "system": {
                                "oneOf": [
                                    {"type": "string"},
                                    {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "type": {"type": "string", "enum": ["text"]},
                                                "text": {"type": "string"},
                                            },
                                        },
                                    },
                                ],
                                "description": "系统提示词",
                            },
                            "messages": {
                                "type": "array",
                                "description": "对话消息列表",
                                "items": {
                                    "type": "object",
                                    "required": ["role", "content"],
                                    "properties": {
                                        "role": {
                                            "type": "string",
                                            "enum": ["user", "assistant"],
                                            "description": "消息角色",
                                        },
                                        "content": {
                                            "oneOf": [
                                                {"type": "string"},
                                                {
                                                    "type": "array",
                                                    "items": {
                                                        "type": "object",
                                                        "properties": {
                                                            "type": {
                                                                "type": "string",
                                                                "enum": ["text", "image"],
                                                            },
                                                            "text": {"type": "string"},
                                                        },
                                                    },
                                                },
                                            ],
                                            "description": "消息内容",
                                        },
                                    },
                                },
                            },
                            "temperature": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                                "description": "采样温度",
                            },
                            "top_p": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                                "description": "核采样参数",
                            },
                            "stream": {
                                "type": "boolean",
                                "description": "是否启用流式输出",
                                "default": False,
                            },
                            "stop_sequences": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "停止序列",
                            },
                        },
                    },
                    "examples": {
                        "basic": {
                            "summary": "基本对话",
                            "value": ANTHROPIC_MESSAGES_EXAMPLE,
                        },
                    },
                }
            },
        }
    },
)
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
        if "messages" not in body:
            return JSONResponse(
                status_code=422,
                content={"type": "error", "error": {"type": "invalid_request_error", "message": "Field 'messages' is required"}}
            )
        stream = body.get("stream", False)
        original_model = body.get("model", "unknown")
        
        # 将 Anthropic 请求体转换为 OpenAI 格式
        openai_body = anthropic_to_openai_request(body)
        mapped_model = openai_body["model"]
        
        logger.info("Anthropic 格式请求: model=%s → %s, stream=%s",
                     original_model, mapped_model, stream)

        try:
            proxy = get_proxy()
        except IFlowNotConfiguredError as e:
            return JSONResponse(
                status_code=503,
                content={"type": "error", "error": {"type": "iflow_not_configured", "message": str(e)}}
            )

        if stream:
            # 流式响应 - 转换为 Anthropic SSE 格式
            # 加载配置以获取思考链设置
            from .settings import load_settings
            settings = load_settings()
            preserve_reasoning = settings.preserve_reasoning_content
            
            # 整个流式传输过程都在锁内进行
            async def generate_anthropic_stream_with_lock():
                """在锁内完成整个流式传输（含 tool_use 支持）"""
                async with _api_request_lock:
                    logger.debug("获取上游流式响应 (Anthropic)...")
                    stream_gen = await proxy.chat_completions(openai_body, stream=True)

                    # 发送 message_start
                    yield create_anthropic_stream_message_start(mapped_model).encode('utf-8')

                    output_tokens = 0
                    buffer = ""
                    block_index = 0
                    stop_reason = "end_turn"

                    # 文本/思考块状态
                    current_text_block_type = None   # None | "text" | "thinking"
                    current_text_block_index = -1

                    # 工具调用块状态: openai_tc_index → {block_index, id}
                    tool_call_block_map: dict = {}
                    current_tc_index = -1  # 当前正在流式传输的工具调用索引

                    async def _process_parsed_chunk(parsed: dict):
                        """处理单个已解析的 SSE chunk，yield Anthropic 事件"""
                        nonlocal block_index, output_tokens, stop_reason
                        nonlocal current_text_block_type, current_text_block_index
                        nonlocal current_tc_index

                        choices = parsed.get("choices", [])
                        if not choices:
                            return
                        choice = choices[0]
                        delta = choice.get("delta", {})
                        finish_reason = choice.get("finish_reason")

                        # ---- 文本 / 思考内容 ----
                        content, content_type = extract_content_from_delta(delta, preserve_reasoning)
                        if content and content_type:
                            if current_text_block_type != content_type:
                                if current_text_block_type is not None:
                                    yield create_anthropic_content_block_stop(current_text_block_index).encode('utf-8')
                                current_text_block_index = block_index
                                block_index += 1
                                yield create_anthropic_content_block_start(current_text_block_index, content_type).encode('utf-8')
                                current_text_block_type = content_type
                            output_tokens += len(content) // 4
                            delta_type = "thinking_delta" if content_type == "thinking" else "text_delta"
                            yield create_anthropic_content_block_delta(content, current_text_block_index, delta_type).encode('utf-8')

                        # ---- 工具调用 ----
                        tool_calls_delta = delta.get("tool_calls", [])
                        for tc in tool_calls_delta:
                            tc_index = tc.get("index", 0)
                            tc_id = tc.get("id")
                            tc_func = tc.get("function", {})
                            tc_name = tc_func.get("name", "")
                            tc_args = tc_func.get("arguments", "")

                            if tc_index not in tool_call_block_map:
                                # 关闭文本块（如果有）
                                if current_text_block_type is not None:
                                    yield create_anthropic_content_block_stop(current_text_block_index).encode('utf-8')
                                    current_text_block_type = None
                                # 关闭上一个工具调用块（如果有）
                                if current_tc_index >= 0 and current_tc_index in tool_call_block_map:
                                    yield create_anthropic_content_block_stop(
                                        tool_call_block_map[current_tc_index]["block_index"]
                                    ).encode('utf-8')
                                # 开始新工具调用块
                                tc_block_index = block_index
                                block_index += 1
                                tool_call_block_map[tc_index] = {
                                    "block_index": tc_block_index,
                                    "id": tc_id or f"toolu_{uuid.uuid4().hex[:24]}",
                                    "name": tc_name or "",
                                }
                                current_tc_index = tc_index
                                yield create_anthropic_tool_use_block_start(
                                    tc_block_index,
                                    tool_call_block_map[tc_index]["id"],
                                    tool_call_block_map[tc_index]["name"],
                                ).encode('utf-8')

                            # 流式传输参数片段
                            if tc_args:
                                yield create_anthropic_input_json_delta(
                                    tc_args, tool_call_block_map[tc_index]["block_index"]
                                ).encode('utf-8')

                        # ---- finish_reason ----
                        if finish_reason == "tool_calls":
                            stop_reason = "tool_use"
                        elif finish_reason == "stop":
                            stop_reason = "end_turn"
                        elif finish_reason == "length":
                            stop_reason = "max_tokens"

                    async for chunk in stream_gen:
                        if isinstance(chunk, str):
                            chunk_str = chunk
                        else:
                            chunk_str = bytes(chunk).decode('utf-8')
                        buffer += chunk_str

                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            parsed = parse_openai_sse_chunk(line)
                            if parsed:
                                async for evt in _process_parsed_chunk(parsed):
                                    yield evt

                    # 处理剩余 buffer
                    for line in buffer.split("\n"):
                        if line.strip():
                            parsed = parse_openai_sse_chunk(line)
                            if parsed:
                                async for evt in _process_parsed_chunk(parsed):
                                    yield evt

                    # 关闭最后打开的文本块
                    if current_text_block_type is not None:
                        yield create_anthropic_content_block_stop(current_text_block_index).encode('utf-8')

                    # 关闭最后打开的工具调用块
                    if current_tc_index >= 0 and current_tc_index in tool_call_block_map:
                        yield create_anthropic_content_block_stop(
                            tool_call_block_map[current_tc_index]["block_index"]
                        ).encode('utf-8')

                    # 发送结束事件
                    yield create_anthropic_message_delta(stop_reason, output_tokens).encode('utf-8')
                    yield create_anthropic_message_stop().encode('utf-8')

            return StreamingResponse(
                generate_anthropic_stream_with_lock(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            # 非流式响应 - 转换为 Anthropic 格式
            # 使用锁确保同一时间只有一个上游请求
            async with _api_request_lock:
                logger.debug("获取上游非流式响应 (Anthropic)...")
                openai_result = await proxy.chat_completions(openai_body, stream=False)
            logger.debug("收到 OpenAI 格式响应: %s", json.dumps(openai_result, ensure_ascii=False)[:300])
            anthropic_result = openai_to_anthropic_response(openai_result, mapped_model)
            first_block = anthropic_result['content'][0] if anthropic_result['content'] else {}
            first_preview = first_block.get('text') or first_block.get('name') or ''
            logger.debug("Anthropic 格式响应: id=%s, stop_reason=%s, preview=%s",
                         anthropic_result['id'], anthropic_result['stop_reason'], first_preview[:80])
            return JSONResponse(content=anthropic_result)

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    except Exception as e:
        error_msg = str(e)
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                error_data = resp.json()
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
        proxy = get_proxy()
    except IFlowNotConfiguredError as e:
        return create_error_response(503, str(e), "iflow_not_configured")
    
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes.decode("utf-8"))
        
        # 简单启发式：如果请求中没有 choices 相关字段，默认使用 Anthropic 格式
        # 因为 CCR 主要使用 Anthropic 格式
        # 但为了安全起见，默认使用 OpenAI 格式
        stream = body.get("stream", False)
        model = body.get("model", "unknown")
        
        if stream:
            # 流式响应 - 整个流式传输过程都在锁内进行
            async def generate_with_lock():
                """在锁内完成整个流式传输"""
                async with _api_request_lock:
                    logger.debug("获取上游流式响应 (root_post)...")
                    stream_gen = await proxy.chat_completions(body, stream=True)
                    chunk_count = 0
                    try:
                        async for chunk in stream_gen:
                            chunk_count += 1
                            yield chunk
                    finally:
                        logger.debug("流式完成 (root_post): 共 %d chunks", chunk_count)
            
            return StreamingResponse(
                generate_with_lock(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        else:
            # 使用锁确保同一时间只有一个上游请求
            async with _api_request_lock:
                logger.debug("获取上游非流式响应 (root_post)...")
                result = await proxy.chat_completions(body, stream=False)
            # 验证响应包含有效的 choices
            if not result.get("choices"):
                logger.error("API 响应缺少 choices 数组 (root_post): %s", json.dumps(result, ensure_ascii=False)[:500])
                raise HTTPException(status_code=500, detail="API 响应格式错误: 缺少 choices 数组")
            return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/models")
async def list_models_compat():
    """Models API - 兼容不带 /v1 前缀的请求"""
    return await list_models()


# ============ Anthropic SDK 兼容端点 ============

@app.post(
    "/api/event_logging/batch",
    summary="事件日志批量上报 (Anthropic SDK 兼容)",
    description="处理 Anthropic SDK 的事件日志请求，直接返回成功响应",
    tags=["Anthropic SDK 兼容"],
)
async def event_logging_batch(request: Request):
    """处理 Anthropic SDK 事件日志请求
    
    Anthropic SDK 会发送事件日志到这个端点，
    我们直接返回成功响应，避免 404 错误。
    """
    # 可以选择记录日志或忽略
    # body = await request.body()
    # print(f"[iflow2api] 事件日志: {body[:200]}")
    return {"status": "ok", "logged": True}


@app.post(
    "/v1/messages/count_tokens",
    summary="Token 计数 (Anthropic SDK 兼容)",
    description="估算请求的 token 数量",
    tags=["Anthropic SDK 兼容"],
)
async def count_tokens(request: Request):
    """估算 token 数量
    
    Anthropic SDK 会调用此端点估算 token 消耗。
    由于我们无法精确计算上游模型的 token 数，
    返回一个估算值。
    """
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes.decode("utf-8"))
        
        # 简单估算：计算消息文本的字符数，除以 4 得到大致的 token 数
        messages = body.get("messages", [])
        system = body.get("system", "")
        
        total_chars = len(str(system))
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        total_chars += len(block.get("text", ""))
            else:
                total_chars += len(str(content))
        
        # L-06: 语言感知 token 估算：中文约 1.5 字/token，英文约 4 字/token
        cjk_chars = sum(1 for c in str(system) + "".join(
            (block.get("text", "") if isinstance(block, dict) and block.get("type") == "text" else str(msg.get("content", "")) if not isinstance(msg.get("content"), list) else "")
            for msg in messages
            for block in (msg.get("content") if isinstance(msg.get("content"), list) else [msg])
        ) if '\u4e00' <= c <= '\u9fff')
        ascii_chars = total_chars - cjk_chars
        estimated_tokens = max(1, int(cjk_chars / 1.5 + ascii_chars / 4.0))
        
        return {
            "input_tokens": estimated_tokens
        }
    except Exception as e:
        # 出错时返回一个默认值
        logger.warning("count_tokens 错误: %s", e)
        return {"input_tokens": 100}


def main():
    """主入口"""
    import argparse
    import uvicorn
    from .settings import load_settings
    from .logging_setup import setup_file_logging

    # 初始化文件日志（CLI 模式：日志同时写入文件和终端）
    setup_file_logging()

    # 解析命令行参数
    parser = argparse.ArgumentParser(
        prog='iflow2api',
        description='iFlow CLI AI 服务代理 - OpenAI 兼容 API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  iflow2api                    # 使用默认配置启动
  iflow2api --port 28001       # 指定端口
  iflow2api --host 0.0.0.0     # 监听所有网卡
  iflow2api --version          # 显示版本信息

配置文件位置:
  ~/.iflow2api/config.json     # 应用配置
  ~/.iflow/settings.json       # iFlow CLI 配置

更多信息请访问: https://github.com/cacaview/iflow2api
        '''
    )
    parser.add_argument('--host', default=None, help='监听地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=None, help='监听端口 (默认: 28000)')
    parser.add_argument('--version', action='store_true', help='显示版本信息')
    args = parser.parse_args()

    # --version 处理
    if args.version:
        print(f"iflow2api {get_version()}")
        sys.exit(0)

    # 加载配置（需要在检查登录状态之前加载，以便获取端口信息）
    settings = load_settings()

    # 检查是否已登录（Docker 环境下允许无配置启动，用户可通过 WebUI 登录）
    if not check_iflow_login():
        if is_docker():
            logger.warning("iFlow 未登录，请通过 WebUI 完成登录")
            logger.warning("访问 http://localhost:%d/admin 进入管理界面", settings.port)
        else:
            logger.error("iFlow 未登录，请先运行 'iflow' 命令并完成登录")
            sys.exit(1)

    # 命令行参数优先于配置文件
    host = args.host if args.host else settings.host
    port = args.port if args.port else settings.port

    # 打印启动信息
    logger.info("%s", get_startup_info())
    logger.info("  监听地址: %s:%d", host, port)

    # 显示快速入门引导
    _show_quick_start_guide(port)

    # 启动服务 - 直接传入 app 对象而非字符串，避免打包后导入失败
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=False,
            log_config=None,  # 不覆盖我们在 setup_file_logging() 中配置的日志 handler
        )
    except OSError as e:
        # 端口冲突友好提示
        if "Address already in use" in str(e) or getattr(e, 'errno', None) in (48, 98, 10048):
            logger.error("端口 %d 已被占用", port)
            logger.error("请使用 --port 指定其他端口，例如: iflow2api --port %d", port + 1)
            logger.error("或修改配置文件 ~/.iflow2api/config.json 中的 port 字段")
        raise


def _show_quick_start_guide(port: int):
    """显示快速入门引导"""
    logger.info("")
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║                    快速入门指南                           ║")
    logger.info("╠══════════════════════════════════════════════════════════╣")
    logger.info("║  API 端点: http://localhost:%-5d/v1                    ║", port)
    logger.info("║  模型列表: http://localhost:%-5d/v1/models             ║", port)
    logger.info("║  管理界面: http://localhost:%-5d/admin                 ║", port)
    logger.info("║  API 文档: http://localhost:%-5d/docs                  ║", port)
    logger.info("╠══════════════════════════════════════════════════════════╣")
    logger.info("║  使用示例:                                                ║")
    logger.info("║  curl http://localhost:%-5d/v1/models                  ║", port)
    logger.info("╚══════════════════════════════════════════════════════════╝")
    logger.info("")


if __name__ == "__main__":
    main()