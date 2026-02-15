"""API 代理服务 - 转发请求到 iFlow API"""

import hmac
import hashlib
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
    - 签名内容: `{user-agent}:{session-id}:{timestamp}`
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
                "id": "kimi-k2-thinking",
                "name": "Kimi-K2-Thinking",
                "description": "Moonshot Kimi K2 思考模型",
            },
            {
                "id": "minimax-m2.5",
                "name": "MiniMax-M2.5",
                "description": "MiniMax M2.5",
            },
            {
                "id": "kimi-k2.5",
                "name": "Kimi-K2.5",
                "description": "Moonshot Kimi K2.5",
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
            # 对于流式请求，我们需要在返回迭代器之前检查状态码
            # 使用上下文管理器手动控制响应
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=request_body,
                timeout=httpx.Timeout(300.0, connect=10.0),
            )
            try:
                response.raise_for_status()
                # 如果成功，返回一个生成器来迭代内容
                # 注意：我们需要确保 response 在迭代完之前不被关闭
                async def content_generator():
                    try:
                        async for chunk in response.aiter_bytes():
                            yield chunk
                    finally:
                        await response.aclose()
                
                return content_generator()
            except Exception:
                await response.aclose()
                raise
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
            response = await client.post(
                url, headers=self._get_headers(), json=body, timeout=httpx.Timeout(300.0, connect=10.0)
            )
            try:
                response.raise_for_status()
                async def content_generator():
                    try:
                        async for chunk in response.aiter_bytes():
                            yield chunk
                    finally:
                        await response.aclose()
                return content_generator()
            except Exception:
                await response.aclose()
                raise

        if method.upper() == "GET":
            response = await client.get(url, headers=self._get_headers())
        elif method.upper() == "POST":
            response = await client.post(url, headers=self._get_headers(), json=body)
        else:
            raise ValueError(f"不支持的 HTTP 方法: {method}")

        response.raise_for_status()
        return response.json()

