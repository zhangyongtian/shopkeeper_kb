# 运行依赖与连接信息（开发环境）

本项目默认通过 `services/docker-compose.yml` 一键启动依赖服务。该 compose 不挂载任何 volume，也不 bind mount；容器删除后数据随之删除。

## 启动与清理

启动：

```bash
docker compose -f services/docker-compose.yml up -d
```

启动（包含 Redis；需要本机已存在 redis 镜像或可访问 Docker Hub 拉取）：

```bash
docker compose -f services/docker-compose.yml --profile cache up -d
```

查看状态：

```bash
docker compose -f services/docker-compose.yml ps
```

停止并删除容器（数据随容器删除）：

```bash
docker compose -f services/docker-compose.yml down
```

## 端口一览

- MongoDB: `27017`
- Redis: `6379`（profile: cache）
- MinIO S3 API: `9002`
- MinIO Console: `9003`
- Milvus: `19530`（gRPC）, `9091`（health）
- Attu（Milvus UI）: `7000`

## 访问地址（局域网示例）

按你的机器 IP 修改（下列以 `192.168.25.133` 为例）：

- MinIO Console: `http://192.168.25.133:9003`（默认账号密码见下）
- MinIO S3 访问基址（用于 Markdown 链接）：`http://192.168.25.133:9002`
- Attu（Milvus UI）: `http://192.168.25.133:7000`
- MongoDB: `mongodb://192.168.25.133:27017`
- Redis: `redis://192.168.25.133:6379/0`

Attu 连接 Milvus 时：

- 若在 Attu 页面里手动填写地址，推荐填写 `standalone:19530`（已在 compose 中为 Milvus 服务添加该别名）
- 也可填写 `milvus:19530`

## 环境变量（.env）

请参考 `.env.example`，建议在本地 `.env` 配置（不要提交）。

### MongoDB

```env
MONGO_URI=mongodb://127.0.0.1:27017
MONGO_DB=shopkeeper_kb
```

### Redis（图片描述缓存）

```env
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_CACHE_TTL_S=2592000
```

### MinIO（图片与图片元数据）

```env
MINIO_ENDPOINT=127.0.0.1:9002
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=shopkeeper-kb
MINIO_SECURE=false
MINIO_PUBLIC_BASE_URL=http://192.168.25.133:9002
```

说明：

- `MINIO_ENDPOINT` 用于服务端 SDK 连接（不带协议）
- `MINIO_PUBLIC_BASE_URL` 用于写回 Markdown 链接（带 `http://`）
- `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` 同时也是 MinIO Console 登录凭据（默认 `minioadmin` / `minioadmin`）
- 程序会自动创建 bucket `shopkeeper-kb` 并设置为匿名可读（公开读，用于 Markdown 直链）

### 千问多模态（OpenAI Compatible）

```env
QWEN_API_KEY=
QWEN_BASE_URL=
QWEN_VL_MODEL=qwen3-vl-flash
QWEN_TIMEOUT_S=60
QWEN_MAX_RETRY=6
QWEN_CONCURRENCY=2
QWEN_RPS=1
```

## 与代码的对应关系

- 配置读取：[settings.py](file:///home/roott/work/src/shopkeeper_kb/settings.py)
- Mongo 客户端：[mongo.py](file:///home/roott/work/src/shopkeeper_kb/tools/mongo.py)
- Redis 客户端：[redis_client.py](file:///home/roott/work/src/shopkeeper_kb/tools/redis_client.py)
- MinIO 客户端：[minio_client.py](file:///home/roott/work/src/shopkeeper_kb/tools/minio_client.py)
- 千问多模态调用：[qwen_vl_api.py](file:///home/roott/work/src/shopkeeper_kb/integrations/qwen_vl_api.py)
