"""iFlow OAuth 认证实现"""

import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timedelta


class IFlowOAuth:
    """iFlow OAuth 认证客户端"""

    # iFlow OAuth 配置
    CLIENT_ID = "10009311001"
    CLIENT_SECRET = "4Z3YjXycVsQvyGF1etiNlIBB4RsqSDtW"
    TOKEN_URL = "https://iflow.cn/oauth/token"
    USER_INFO_URL = "https://iflow.cn/api/oauth/getUserInfo"
    AUTH_URL = "https://iflow.cn/oauth"

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_token(
        self, code: str, redirect_uri: str = "http://localhost:11451/oauth2callback"
    ) -> Dict[str, Any]:
        """
        使用授权码获取 OAuth token

        Args:
            code: OAuth 授权码
            redirect_uri: 回调地址

        Returns:
            包含 access_token, refresh_token, expires_in 等字段的字典

        Raises:
            httpx.HTTPError: HTTP 请求失败
            ValueError: 响应数据格式错误
        """
        import base64

        client = await self._get_client()

        # 使用 Basic Auth
        credentials = base64.b64encode(
            f"{self.CLIENT_ID}:{self.CLIENT_SECRET}".encode()
        ).decode()

        response = await client.post(
            self.TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.CLIENT_ID,
                "client_secret": self.CLIENT_SECRET,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Authorization": f"Basic {credentials}",
            },
        )
        response.raise_for_status()

        token_data = response.json()

        if "access_token" not in token_data:
            raise ValueError("OAuth 响应缺少 access_token")

        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            token_data["expires_at"] = datetime.now() + timedelta(seconds=expires_in)

        return token_data

    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """刷新 token"""
        import base64

        client = await self._get_client()

        credentials = base64.b64encode(
            f"{self.CLIENT_ID}:{self.CLIENT_SECRET}".encode()
        ).decode()

        response = await client.post(
            self.TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self.CLIENT_ID,
                "client_secret": self.CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Authorization": f"Basic {credentials}",
            },
        )

        if response.status_code == 400:
            error_data = response.json()
            if "invalid_grant" in error_data.get("error", ""):
                raise ValueError("refresh_token 无效或已过期")

        response.raise_for_status()

        token_data = response.json()

        if "access_token" not in token_data:
            raise ValueError("OAuth 响应缺少 access_token")

        if "expires_in" in token_data:
            expires_in = token_data["expires_in"]
            token_data["expires_at"] = datetime.now() + timedelta(seconds=expires_in)

        return token_data

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        获取用户信息（包含 API Key）

        Args:
            access_token: 访问令牌

        Returns:
            用户信息字典

        Raises:
            httpx.HTTPError: HTTP 请求失败
            ValueError: 响应数据格式错误或 access_token 无效
        """
        from urllib.parse import quote

        client = await self._get_client()

        # 使用查询参数传递 access_token
        url = f"{self.USER_INFO_URL}?accessToken={quote(access_token)}"

        response = await client.get(
            url,
            headers={"Accept": "application/json"},
        )

        if response.status_code == 401:
            raise ValueError("access_token 无效或已过期")

        response.raise_for_status()

        result = response.json()

        if result.get("success") and result.get("data"):
            return result["data"]
        else:
            raise ValueError("获取用户信息失败")

    def get_auth_url(
        self,
        redirect_uri: str = "http://localhost:11451/oauth2callback",
        state: Optional[str] = None,
    ) -> str:
        """
        生成 OAuth 授权 URL

        Args:
            redirect_uri: 回调地址
            state: CSRF 防护令牌

        Returns:
            OAuth 授权 URL
        """
        import secrets

        if state is None:
            state = secrets.token_urlsafe(16)

        return (
            f"{self.AUTH_URL}?"
            f"client_id={self.CLIENT_ID}&"
            f"loginMethod=phone&"
            f"type=phone&"
            f"redirect={redirect_uri}&"
            f"state={state}"
        )

    async def validate_token(self, access_token: str) -> bool:
        """验证 access_token 是否有效"""
        try:
            await self.get_user_info(access_token)
            return True
        except (httpx.HTTPError, ValueError):
            return False

    def is_token_expired(
        self, expires_at: Optional[datetime], buffer_seconds: int = 300
    ) -> bool:
        """检查 token 是否即将过期"""
        if expires_at is None:
            return False
        return datetime.now() >= (expires_at - timedelta(seconds=buffer_seconds))
