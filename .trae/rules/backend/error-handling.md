# Backend Error Handling（Python 常规项目规范）

本规则用于统一后端错误处理、日志与对外错误返回，目标：对用户友好、对开发可排障、对系统安全。

## 1. 总体原则

- 对外错误信息要“可理解但不泄露内部细节”
- 任何异常必须：
  - 记录日志（包含 request_id）
  - 返回结构化错误响应（JSON）
  - 使用合适的 HTTP 状态码
- 业务错误与系统错误区分处理

## 2. 统一错误响应格式

所有非 2xx 响应使用统一结构：

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": {},
    "request_id": "string"
  }
}
```

字段约定：
- `code`：稳定的机器可读错误码（用于前端/客户端分支处理）
- `message`：面向用户/调用方的简短说明（英文或中文保持一致，项目内建议英文）
- `details`：可选，提供参数名、校验失败列表等（不要放敏感信息）
- `request_id`：每个请求必带，方便日志定位

## 3. HTTP 状态码约定

- `400 Bad Request`：参数格式错误/缺失/无法解析
- `401 Unauthorized`：未认证（无 token/无凭据）
- `403 Forbidden`：已认证但无权限
- `404 Not Found`：资源不存在
- `409 Conflict`：冲突（重复创建、版本冲突等）
- `422 Unprocessable Entity`：校验失败（FastAPI/Pydantic 常见）
- `429 Too Many Requests`：限流
- `500 Internal Server Error`：未分类服务端错误
- `502/503/504`：上游依赖故障/不可用/超时

## 4. 业务错误码命名规范

- 采用大写下划线或点分层皆可，但必须全项目统一
- 推荐：`<DOMAIN>_<REASON>` 或 `<domain>.<reason>`
- 示例：
  - `AUTH_INVALID_TOKEN`
  - `KB_DOCUMENT_NOT_FOUND`
  - `MILVUS_QUERY_FAILED`
  - `MONGO_DUPLICATE_KEY`

## 5. 异常分层与处理策略

- 输入校验错误：直接返回 422/400，details 给出字段与原因
- 业务规则错误：返回 409/400（按语义），code 稳定
- 外部依赖错误（Mongo/MinIO/Milvus/LLM）：
  - 超时/不可用：返回 503/504
  - 上游返回可解析错误：映射为明确 code（例如 `MINIO_ACCESS_DENIED`）
- 未捕获异常：统一兜底 500

## 6. 日志规范（可排障且不泄露）

- 必须输出：
  - `request_id`
  - `method`, `path`, `status_code`, `latency_ms`
  - 关键业务维度（如 `user_id`、`job_id`，可选）
- 严禁记录：
  - 明文密码、token、secret key、Mongo URI 中的凭据
  - `.env` 内容、私钥、公钥材料（除非已脱敏）
- 错误日志需要包含堆栈（仅服务端日志），但对外响应不包含堆栈

## 7. FastAPI 落地建议

- 使用全局异常处理器：
  - Pydantic/RequestValidationError → 422
  - 自定义业务异常（如 `AppError`）→ 映射到状态码 + error.code
  - 兜底 `Exception` → 500
- 为每个请求注入 request_id：
  - header 优先：`X-Request-Id`
  - 未提供则服务端生成，并在响应 header 与 body 返回

## 8. 返回内容的安全要求

- 认证失败不要提示“用户名存在/不存在”
- 数据库错误不要原样返回（例如 duplicate key 的集合名/索引名可在日志里保留，对外只给通用 message）
- 当错误可能暴露内部资源结构（路径、bucket 名、集合名）时，details 要审慎

## 9. 重试与幂等提示

- 503/504 可以提示“稍后重试”
- 对可重试的上游错误返回 code（例如 `UPSTREAM_TIMEOUT`），便于客户端实现自动重试
