"""API 代理服务 - 转发请求到 iFlow API"""

import hmac
import hashlib
import json
import time
import uuid

import httpx
from typing import AsyncIterator, Optional
from .config import IFlowConfig


# iFlow CLI 特殊 User-Agent，用于解锁更多模型
IFLOW_CLI_USER_AGENT = "iFlow-Cli"


def generate_signature(user_agent: str, session_id: str, timestamp: int, api_key: str) -> str | None:
    """
    生成 iFlow API 签名 (HMAC-SHA256)
    
    签名算法来源于 iflow-cli 源码:
    - 算法: HMAC-SHA256
    - 密钥: apiKey
    - 签名内容: `{user_agent}:{session_id}:{timestamp}`
    - 输出: 十六进制字符串
    """
    if not api_key:
        return None
    message = f"{user_agent}:{session_id}:{timestamp}"
    try:
        return hmac.new(
            api_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    except Exception as e:
        print(f"[iflow2api] Failed to generate HMAC signature: {e}")
        return None


class IFlowProxy:
    """iFlow API 代理"""

    def __init__(self, config: IFlowConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        # 保持会话一致性
        self._session_id = str(uuid.uuid4())
        self._conversation_id = str(uuid.uuid4())

    def _get_headers(self) -> dict:
        """
        获取请求头
        
        模仿 iFlow CLI 的请求头设置:
        - user-agent: iFlow-Cli
        - session-id: 会话ID
        - conversation-id: 对话ID
        - x-iflow-signature: HMAC-SHA256 签名
        - x-iflow-timestamp: 时间戳(毫秒)
        - installation-id: 安装ID
        """
        timestamp = int(time.time() * 1000)  # 毫秒时间戳
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "User-Agent": IFLOW_CLI_USER_AGENT,
            "session-id": self._session_id,
            "conversation-id": self._conversation_id,
            "Accept": "application/json",
        }
        
        # 添加 installation-id
        if self.config.installation_id:
            headers["installation-id"] = self.config.installation_id
        
        # 添加签名
        signature = generate_signature(
            IFLOW_CLI_USER_AGENT,
            self._session_id,
            timestamp,
            self.config.api_key
        )
        if signature:
            headers["x-iflow-signature"] = signature
            headers["x-iflow-timestamp"] = str(timestamp)
        
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    @staticmethod
    def _normalize_response(result: dict) -> dict:
        """
        规范化 OpenAI 格式响应
        
        某些模型（如 GLM-5）使用 reasoning_content 而非 content 返回内容，
        导致 OpenAI 兼容客户端无法读取助手消息。
        此方法确保 content 字段始终包含有效内容。
        """
        choices = result.get("choices", [])
        for choice in choices:
            message = choice.get("message", {})
            content = message.get("content")
            reasoning_content = message.get("reasoning_content")
            
            if not content and reasoning_content:
                # content 为空但 reasoning_content 有值 → 移动到 content
                print(f"[iflow2api] 规范化: reasoning_content → content (len={len(reasoning_content)})")
                message["content"] = reasoning_content
            elif content and reasoning_content:
                # 两者都有值 → 保留 content，记录日志
                print(f"[iflow2api] 响应包含 content(len={len(content)}) 和 reasoning_content(len={len(reasoning_content)})")
            elif not content and not reasoning_content:
                print(f"[iflow2api] 警告: message 中 content 和 reasoning_content 均为空")
                print(f"[iflow2api] message keys: {list(message.keys())}")
        
        return result

    @staticmethod
    def _normalize_stream_chunk(chunk_data: dict) -> dict:
        """
        规范化流式响应中的 delta
        
        将 delta 中的 reasoning_content 移动到 content（不保留 reasoning_content）。
        这确保只看 content 字段的 OpenAI 兼容客户端能正常工作，
        同时避免内容重复（reasoning_content 和 content 显示同样的文本）。
        """
        choices = chunk_data.get("choices", [])
        for choice in choices:
            delta = choice.get("delta", {})
            content = delta.get("content")
            reasoning_content = delta.get("reasoning_content")
            
            if not content and reasoning_content:
                # 将 reasoning_content 移动到 content
                delta["content"] = reasoning_content
                del delta["reasoning_content"]
        
        return chunk_data

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_models(self) -> dict:
        """
        获取可用模型列表

        iFlow API 没有公开的 /models 端点，因此返回已知的模型列表。
        模型列表来源于 iflow-cli 源码中的 SUPPORTED_MODELS。
        使用 iFlow-Cli User-Agent 可以解锁这些高级模型。
        """
        # iFlow CLI 支持的模型列表 (来源: iflow-cli SUPPORTED_MODELS)
        # https://github.com/iflow-ai/iflow-cli/blob/main/src/models.ts
        # 2026.2.15 更新
        models = [
            {"id": "glm-4.6", "name": "GLM-4.6", "description": "智谱 GLM-4.6"},
            {"id": "glm-4.7", "name": "GLM-4.7", "description": "智谱 GLM-4.7"},
            {"id": "glm-5", "name": "GLM-5", "description": "智谱 GLM-5 (推荐)"},
            {
                "id": "iFlow-ROME-30BA3B",
                "name": "iFlow-ROME-30BA3B",
                "description": "iFlow ROME 30B (快速)",
            },
            {
                "id": "deepseek-v3.2-chat",
                "name": "DeepSeek-V3.2",
                "description": "DeepSeek V3.2 对话模型",
            },
            {
                "id": "qwen3-coder-plus",
                "name": "Qwen3-Coder-Plus",
                "description": "通义千问 Qwen3 Coder Plus",
            },
            {
                "id": "kimi-k2",
                "name": "Kimi-K2",
                "description": "Moonshot Kimi K2",
            },
            {
                "id": "kimi-k2-thinking",
                "name": "Kimi-K2-Thinking",
                "description": "Moonshot Kimi K2 思考模型",
            },
            {
                "id": "kimi-k2.5",
                "name": "Kimi-K2.5",
                "description": "Moonshot Kimi K2.5",
            },
            {
                "id": "minimax-m2.5",
                "name": "MiniMax-M2.5",
                "description": "MiniMax M2.5",
            },
        ]

        import time

        current_time = int(time.time())

        # 返回 OpenAI 兼容格式
        return {
            "object": "list",
            "data": [
                {
                    "id": model["id"],
                    "object": "model",
                    "created": current_time,
                    "owned_by": "iflow",
                    "permission": [],
                    "root": model["id"],
                    "parent": None,
                }
                for model in models
            ],
        }

    async def chat_completions(
        self,
        request_body: dict,
        stream: bool = False,
    ) -> dict | AsyncIterator[bytes]:
        """
        调用 chat completions API

        Args:
            request_body: 请求体
            stream: 是否流式响应

        Returns:
            非流式: 返回完整响应 dict
            流式: 返回字节流迭代器
        """
        client = await self._get_client()

        if stream:
            # 对于流式请求，使用 httpx 的 stream 方法实现真正的流式传输
            # 注意：不能使用 await client.post()，因为它会等待整个响应体下载完成
            async def stream_generator():
                buffer = b""
                chunk_count = 0
                try:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers=self._get_headers(),
                        json=request_body,
                        timeout=httpx.Timeout(300.0, connect=10.0),
                    ) as response:
                        # 检查状态码
                        response.raise_for_status()
                        
                        # 记录上游响应信息以便调试
                        content_type = response.headers.get("content-type", "unknown")
                        print(f"[iflow2api] 上游响应: status={response.status_code}, content-type={content_type}")
                        
                        # 如果上游没有返回 SSE 流（可能是 JSON 错误），读取并处理
                        if "text/event-stream" not in content_type and "application/octet-stream" not in content_type:
                            # 上游返回了非流式响应（可能是错误）
                            raw_body = await response.aread()
                            body_str = raw_body.decode("utf-8", errors="replace")
                            print(f"[iflow2api] 上游非流式响应体: {body_str[:500]}")
                            try:
                                error_data = json.loads(body_str)
                                error_msg = error_data.get("msg") or error_data.get("error", {}).get("message") or body_str[:200]
                            except json.JSONDecodeError:
                                error_msg = body_str[:200] or "上游返回空响应"
                            
                            # 生成一个包含错误信息的 SSE chunk
                            error_chunk = {
                                "id": f"error-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": request_body.get("model", "unknown"),
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": f"[API Error] {error_msg}"},
                                    "finish_reason": "stop"
                                }]
                            }
                            yield ("data: " + json.dumps(error_chunk, ensure_ascii=False) + "\n\n").encode("utf-8")
                            yield b"data: [DONE]\n\n"
                            return
                        
                        # 流式读取响应
                        async for chunk in response.aiter_bytes():
                            buffer += chunk
                            # 按行处理 SSE 数据
                            while b"\n" in buffer:
                                line, buffer = buffer.split(b"\n", 1)
                                line_str = line.decode("utf-8", errors="replace").strip()
                                if not line_str:
                                    yield b"\n"
                                    continue
                                chunk_count += 1
                                if line_str.startswith("data:"):
                                    data_str = line_str[5:].strip()
                                    if data_str == "[DONE]":
                                        yield b"data: [DONE]\n\n"
                                        continue
                                    try:
                                        chunk_data = json.loads(data_str)
                                        chunk_data = self._normalize_stream_chunk(chunk_data)
                                        yield ("data: " + json.dumps(chunk_data, ensure_ascii=False) + "\n\n").encode("utf-8")
                                    except (json.JSONDecodeError, Exception):
                                        # 无法解析的 chunk 原样传递
                                        yield (line_str + "\n").encode("utf-8")
                                else:
                                    yield (line_str + "\n").encode("utf-8")
                        
                        # 处理 buffer 中剩余数据（不以 \n 结尾的最后部分）
                        if buffer:
                            line_str = buffer.decode("utf-8", errors="replace").strip()
                            if line_str.startswith("data:"):
                                data_str = line_str[5:].strip()
                                if data_str != "[DONE]":
                                    try:
                                        chunk_data = json.loads(data_str)
                                        chunk_data = self._normalize_stream_chunk(chunk_data)
                                        yield ("data: " + json.dumps(chunk_data, ensure_ascii=False) + "\n\n").encode("utf-8")
                                    except (json.JSONDecodeError, Exception):
                                        yield (line_str + "\n").encode("utf-8")
                                else:
                                    yield b"data: [DONE]\n\n"
                            elif line_str:
                                yield (line_str + "\n").encode("utf-8")
                                
                except Exception as e:
                    print(f"[iflow2api] 流式请求错误: {e}")
                    raise
                finally:
                    if chunk_count == 0:
                        print(f"[iflow2api] 警告: 上游流式响应为空 (0 chunks)")
                    else:
                        print(f"[iflow2api] 流式完成: 共 {chunk_count} chunks")
            
            return stream_generator()
        else:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=request_body,
            )
            response.raise_for_status()
            result = response.json()

            # 确保 usage 统计信息存在 (OpenAI 兼容)
            if "usage" not in result:
                result["usage"] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                }

            # 规范化响应: 确保 content 字段有效
            # GLM-5 等推理模型可能只返回 reasoning_content 而 content 为 null
            # OpenAI 兼容客户端（如 Kilo Code）只检查 content 字段
            result = self._normalize_response(result)

            return result

    async def proxy_request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        stream: bool = False,
    ) -> dict | AsyncIterator[bytes]:
        """
        通用请求代理

        Args:
            method: HTTP 方法
            path: API 路径 (不含 base_url)
            body: 请求体
            stream: 是否流式响应

        Returns:
            响应数据
        """
        client = await self._get_client()
        url = f"{self.base_url}{path}"

        if stream and method.upper() == "POST":
            # 使用 httpx 的 stream 方法实现真正的流式传输
            async def stream_gen():
                try:
                    async with client.stream(
                        "POST",
                        url,
                        headers=self._get_headers(),
                        json=body,
                        timeout=httpx.Timeout(300.0, connect=10.0),
                    ) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes():
                            yield chunk
                except Exception as e:
                    print(f"[iflow2api] proxy_request 流式错误: {e}")
                    raise
            return stream_gen()

        if method.upper() == "GET":
            response = await client.get(url, headers=self._get_headers())
        elif method.upper() == "POST":
            response = await client.post(url, headers=self._get_headers(), json=body)
        else:
            raise ValueError(f"不支持的 HTTP 方法: {method}")

        response.raise_for_status()
        return response.json()