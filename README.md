## 掌柜智库（shopkeeper-kb）

企业级智能知识库系统骨架工程：FastAPI + MongoDB（后续可接入 Milvus / MinIO / LangGraph 等）。

### 本地运行

```bash
uv sync
uv run shopkeeper-kb
```

### 健康检查

```bash
curl -s http://127.0.0.1:8000/health | python -m json.tool
```
