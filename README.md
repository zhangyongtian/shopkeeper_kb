## 智能知识库（shopkeeper-kb）

智能知识库是一个企业级智能知识库系统骨架工程，面向垂直领域文档（PDF、Markdown 等），基于 RAG（检索增强生成）思路提供知识检索与问答能力。

### 核心能力（骨架）

- 文档导入流水线：多格式导入、结构化解析、切片、元数据提取、向量化入库（后续逐步完善）
- 智能检索问答：混合检索、多路召回融合、重排序、流式输出（后续逐步完善）
- 可观测性：注入并回传 `X-Request-Id`，便于日志关联排障
- 统一错误响应：非 2xx 统一返回 `{ "error": { "code", "message", "details", "request_id" } }`

### 项目结构

```text
src/shopkeeper_kb/
  app/                 FastAPI 应用层（路由/中间件/异常处理）
  workflows/           节点与流程编排（后续接入 LangGraph）
  agents/              运行器与编排入口（后续完善）
  tools/               外部系统访问封装（Mongo/MinIO/Milvus 等）
  integrations/        第三方 SDK/HTTP 客户端封装
  prompts/             Prompt 模板与规范化输入
  settings.py          环境变量与配置加载
  logging_config.py    日志初始化（colorlog）
```

### 配置

复制环境变量模板并按需修改：

```bash
cp .env.example .env
```

关键配置项：

- `API_HOST` / `API_PORT`：服务监听地址与端口
- `LOG_LEVEL`：日志级别（INFO/DEBUG/ERROR 等）
- `MONGO_URI` / `MONGO_DB`：MongoDB 连接与库名

### 本地运行

```bash
/home/roott/.local/bin/uv sync
/home/roott/.local/bin/uv run shopkeeper-kb
```

也可使用模块方式启动：

```bash
/home/roott/.local/bin/uv run python -m shopkeeper_kb
```

### 健康检查

```bash
curl -s http://127.0.0.1:8000/health | python -m json.tool
```

### 日志

应用启动时会初始化彩色日志输出。业务代码推荐统一使用：

```python
from shopkeeper_kb import logging_config as log

log.info("message")
log.error("message")
```
