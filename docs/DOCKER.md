# Docker 部署指南

本文档介绍如何使用 Docker 部署 iFlow2API 服务。

## 快速开始

### 使用 Docker Compose（推荐）

```bash
# 克隆仓库
git clone https://github.com/iflow-ai/iflow2api.git
cd iflow2api

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 使用 Docker 命令

```bash
# 构建镜像
docker build -t iflow2api:latest .

# 运行容器
docker run -d \
  --name iflow2api \
  -p 28000:28000 \
  -v ~/.iflow:/home/appuser/.iflow:ro \
  iflow2api:latest

# 查看日志
docker logs -f iflow2api

# 停止容器
docker stop iflow2api
```

## 配置

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `28000` | 监听端口 |

### 挂载配置文件

iFlow2API 需要读取 iFlow CLI 的配置文件来获取 API Key 和 OAuth Token。默认情况下，配置文件位于 `~/.iflow/settings.json`。

```bash
# 挂载 iFlow 配置目录
docker run -d \
  --name iflow2api \
  -p 28000:28000 \
  -v ~/.iflow:/home/appuser/.iflow:ro \
  iflow2api:latest
```

### 使用环境变量配置 API Key

如果不想挂载配置文件，也可以通过环境变量配置：

```bash
docker run -d \
  --name iflow2api \
  -p 28000:28000 \
  -e IFLOW_API_KEY=sk-xxx \
  -e IFLOW_BASE_URL=https://apis.iflow.cn/v1 \
  iflow2api:latest
```

## 健康检查

容器内置健康检查，每 30 秒检查一次服务状态：

```bash
# 查看容器健康状态
docker inspect --format='{{.State.Health.Status}}' iflow2api

# 手动健康检查
curl http://localhost:28000/health
```

## 数据持久化

应用配置（如主题设置、语言设置等）存储在 `~/.iflow2api/` 目录。可以使用 Docker Volume 持久化：

```yaml
volumes:
  - iflow2api-config:/home/appuser/.iflow2api
```

## 多架构支持

Docker 镜像支持以下架构：

- `linux/amd64`
- `linux/arm64`

```bash
# 拉取特定架构的镜像
docker pull --platform linux/amd64 iflow2api:latest
```

## Docker Hub

镜像已发布到 Docker Hub，支持滚动发布策略：

### 可用标签

| 标签 | 说明 | 更新策略 |
|------|------|----------|
| `latest` | 最新稳定版 | 发布新版本时更新 |
| `edge` | 开发版 | main 分支每次推送时更新 |
| `1.1.5` | 特定版本 | 永久保留 |
| `1.1` | 1.1.x 系列最新版 | 该系列发布新版本时更�� |

### 使用示例

```bash
# 拉取最新稳定版（推荐）
docker pull cacaview/iflow2api:latest

# 拉取开发版（体验最新功能）
docker pull cacaview/iflow2api:edge

# 拉取特定版本
docker pull cacaview/iflow2api:1.1.5

# 使用 Docker Hub 镜像运行
docker run -d \
  --name iflow2api \
  -p 28000:28000 \
  -v ~/.iflow:/home/appuser/.iflow:ro \
  cacaview/iflow2api:latest
```

> **注意**：`edge` 标签跟随 main 分支开发进度，可能包含未发布的功能，不建议在生产环境使用。

## 生产环境建议

1. **使用 HTTPS**：建议在 Docker 前面部署反向代理（如 Nginx、Caddy）来处理 HTTPS

2. **资源限制**：设置容器资源限制
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '1'
         memory: 512M
   ```

3. **日志管理**：配置日志轮转
   ```yaml
   logging:
     driver: "json-file"
     options:
       max-size: "10m"
       max-file: "3"
   ```

4. **自动重启**：设置重启策略
   ```yaml
   restart: unless-stopped
   ```

## 故障排除

### 容器无法启动

```bash
# 查看容器日志
docker logs iflow2api

# 检查配置文件是否存在
ls -la ~/.iflow/settings.json
```

### 无法连接到服务

```bash
# 检查端口是否被占用
netstat -tlnp | grep 28000

# 检查防火墙设置
sudo ufw status
```

### 权限问题

如果遇到权限问题，确保挂载的配置文件可读：

```bash
# 检查文件权限
ls -la ~/.iflow/settings.json

# 修改权限
chmod 644 ~/.iflow/settings.json
```

## 相关链接

- [Docker 官方文档](https://docs.docker.com/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [iFlow2API GitHub](https://github.com/your-repo/iflow2api)
