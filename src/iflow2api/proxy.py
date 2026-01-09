"""API 代理服务 - 转发请求到 iFlow API"""

import httpx
from typing import AsyncIterator, Optional
from .config import IFlowConfig


# iFlow CLI 特殊 User-Agent，用于解锁更多模型
IFLOW_CLI_USER_AGENT = "iFlow-Cli"


class IFlowProxy:
    """iFlow API 代理"""

    def __init__(self, config: IFlowConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    def _get_headers(self) -> dict:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "user-agent": IFLOW_CLI_USER_AGENT,  # 小写以匹配 curl 行为
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

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
        models = [
            {"id": "glm-4.7", "name": "GLM-4.7", "description": "智谱 GLM-4.7 (推荐)"},
            {"id": "iFlow-ROME-30BA3B", "name": "iFlow-ROME-30BA3B", "description": "iFlow ROME 30B (快速)"},
            {"id": "deepseek-v3.2-chat", "name": "DeepSeek-V3.2", "description": "DeepSeek V3.2 对话模型"},
            {"id": "qwen3-coder-plus", "name": "Qwen3-Coder-Plus", "description": "通义千问 Qwen3 Coder Plus"},
            {"id": "kimi-k2-thinking", "name": "Kimi-K2-Thinking", "description": "Moonshot Kimi K2 思考模型"},
            {"id": "minimax-m2.1", "name": "MiniMax-M2.1", "description": "MiniMax M2.1"},
            {"id": "kimi-k2-0905", "name": "Kimi-K2-0905", "description": "Moonshot Kimi K2 0905"},
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
            return self._stream_chat_completions(client, request_body)
        else:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=request_body,
            )
            response.raise_for_status()
            return response.json()

    async def _stream_chat_completions(
        self,
        client: httpx.AsyncClient,
        request_body: dict,
    ) -> AsyncIterator[bytes]:
        """流式调用 chat completions API"""
        async with client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._get_headers(),
            json=request_body,
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk

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
            return self._stream_request(client, url, body)

        if method.upper() == "GET":
            response = await client.get(url, headers=self._get_headers())
        elif method.upper() == "POST":
            response = await client.post(
                url, headers=self._get_headers(), json=body
            )
        else:
            raise ValueError(f"不支持的 HTTP 方法: {method}")

        response.raise_for_status()
        return response.json()

    async def _stream_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        body: Optional[dict],
    ) -> AsyncIterator[bytes]:
        """流式请求"""
        async with client.stream(
            "POST",
            url,
            headers=self._get_headers(),
            json=body,
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk
