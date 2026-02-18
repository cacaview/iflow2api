"""测试自定义 API 鉴权功能"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from iflow2api.app import app
from iflow2api.settings import AppSettings


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


@pytest.fixture
def mock_settings_no_auth():
    """模拟无鉴权配置"""
    settings = AppSettings()
    settings.custom_api_key = ""
    settings.custom_auth_header = "Authorization"
    return settings


@pytest.fixture
def mock_settings_with_auth():
    """模拟有鉴权配置"""
    settings = AppSettings()
    settings.custom_api_key = "test-api-key-12345"
    settings.custom_auth_header = "Authorization"
    return settings


@pytest.fixture
def mock_settings_custom_header():
    """模拟自定义标头配置"""
    settings = AppSettings()
    settings.custom_api_key = "test-api-key-12345"
    settings.custom_auth_header = "cs-sk-key"
    return settings


class TestCustomAuth:
    """测试自定义 API 鉴权"""

    def test_no_auth_required_when_key_not_set(self, client, mock_settings_no_auth):
        """测试：未设置密钥时不需要鉴权"""
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_no_auth):
            # 访问 health 端点应该成功
            response = client.get("/health")
            assert response.status_code == 200

    def test_health_endpoint_always_accessible(self, client, mock_settings_with_auth):
        """测试：健康检查端点始终可访问（即使设置了密钥）"""
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_with_auth):
            response = client.get("/health")
            assert response.status_code == 200

    def test_docs_endpoint_always_accessible(self, client, mock_settings_with_auth):
        """测试：文档端点始终可访问（即使设置了密钥）"""
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_with_auth):
            response = client.get("/docs")
            # 可能返回 200 或其他状态码，但不应该是 401
            assert response.status_code != 401

    def test_missing_auth_header_returns_401(self, client, mock_settings_with_auth):
        """测试：设置密钥后，缺少授权标头返回 401"""
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_with_auth):
            # 不带任何授权标头访问 models 端点
            response = client.get("/v1/models")
            assert response.status_code == 401
            assert "error" in response.json()
            assert response.json()["error"]["code"] == "missing_api_key"

    def test_invalid_api_key_returns_401(self, client, mock_settings_with_auth):
        """测试：错误的 API 密钥返回 401"""
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_with_auth):
            # 使用错误的密钥
            response = client.get(
                "/v1/models",
                headers={"Authorization": "Bearer wrong-key"}
            )
            assert response.status_code == 401
            assert "error" in response.json()
            assert response.json()["error"]["code"] == "invalid_api_key"

    def test_correct_api_key_with_bearer_prefix(self, client, mock_settings_with_auth):
        """测试：正确的 API 密钥（Bearer 格式）可以访问"""
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_with_auth):
            # 使用正确的密钥（Bearer 格式）
            response = client.get(
                "/v1/models",
                headers={"Authorization": "Bearer test-api-key-12345"}
            )
            # 应该通过鉴权（具体响应取决于 models 端点的实现）
            # 不应该返回 401
            assert response.status_code != 401

    def test_correct_api_key_without_bearer_prefix(self, client, mock_settings_with_auth):
        """测试：正确的 API 密钥（不带 Bearer）可以访问"""
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_with_auth):
            # 使用正确的密钥（不带 Bearer）
            response = client.get(
                "/v1/models",
                headers={"Authorization": "test-api-key-12345"}
            )
            # 应该通过鉴权
            assert response.status_code != 401

    def test_custom_auth_header_name(self, client, mock_settings_custom_header):
        """测试：自定义授权标头名称（如 cs-sk-key）"""
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_custom_header):
            # 使用自定义标头名称
            response = client.get(
                "/v1/models",
                headers={"cs-sk-key": "test-api-key-12345"}
            )
            # 应该通过鉴权
            assert response.status_code != 401

    def test_custom_header_with_wrong_header_name(self, client, mock_settings_custom_header):
        """测试：使用错误的标头名称应该返回 401"""
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_custom_header):
            # 使用 Authorization 而不是 cs-sk-key
            response = client.get(
                "/v1/models",
                headers={"Authorization": "test-api-key-12345"}
            )
            assert response.status_code == 401

    def test_post_endpoint_with_auth(self, client, mock_settings_with_auth):
        """测试：POST 端点也需要鉴权"""
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_with_auth):
            # 不带授权标头访问 chat completions 端点
            response = client.post(
                "/v1/chat/completions",
                json={"model": "glm-4.7", "messages": [{"role": "user", "content": "hi"}]}
            )
            assert response.status_code == 401

    def test_post_endpoint_with_correct_auth(self, client, mock_settings_with_auth):
        """测试：带正确授权的 POST 请求"""
        # Mock both settings and iflow config
        from iflow2api.config import IFlowConfig
        mock_iflow_config = IFlowConfig(
            api_key="test-iflow-key",
            base_url="https://apis.iflow.cn/v1"
        )
        
        with patch('iflow2api.settings.load_settings', return_value=mock_settings_with_auth), \
             patch('iflow2api.app.load_iflow_config', return_value=mock_iflow_config):
            # 带正确授权标头访问 chat completions 端点
            response = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer test-api-key-12345"},
                json={"model": "glm-4.7", "messages": [{"role": "user", "content": "hi"}]}
            )
            # 应该通过鉴权（具体响应取决于后端实现）
            # 不应该返回 401 (可能返回其他错误，但不是鉴权错误)
            assert response.status_code != 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
