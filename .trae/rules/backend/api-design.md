# Backend API Design（Python 常规项目规范）

本规则用于约束本项目后端 API 的设计方式，目标：一致、可维护、可演进、易于客户端集成与调试。

## 1. 基础约定

- 默认采用 HTTP JSON API（除非明确要求 gRPC/WebSocket）
- 统一字符集 UTF-8
- 统一返回 `application/json`（文件下载/流式除外）
- API 必须可观测：关键请求需有 request_id/trace_id，日志中可关联

## 2. 路径与资源建模

- 以“资源”为中心命名：`/items`、`/documents`、`/jobs`
- 使用复数名词：`/users` 而不是 `/user`
- 路径层级最多 3 层，避免深嵌套
  - 推荐：`/collections/{collection_id}/items`
  - 避免：`/a/{id}/b/{id}/c/{id}/d`
- 用 query 表达筛选/排序/分页，用 body 表达创建/复杂查询条件（必要时）

## 3. HTTP 方法语义

- `GET /resources`：列表（支持筛选/分页/排序）
- `GET /resources/{id}`：详情
- `POST /resources`：创建
- `PATCH /resources/{id}`：局部更新（推荐）
- `PUT /resources/{id}`：全量替换（慎用，要求客户端提供完整对象）
- `DELETE /resources/{id}`：删除
- 触发动作/任务：用 `POST /jobs` 或 `POST /resources/{id}:action`（二选一，保持一致）

## 4. 请求与响应结构

- 请求参数校验必须明确：类型、范围、必填/可选、默认值
- 响应字段命名统一用 `snake_case`
- 对外 API 禁止直接暴露内部字段名/数据库字段名（如 `_id`），需要做适配/映射
- 禁止返回超大对象：列表接口默认做字段裁剪或分页

### 4.1 成功响应

- `GET` 返回实体或列表
- `POST` 创建成功返回 `201`，body 返回新资源，包含 `id`
- `DELETE` 成功返回 `204`（无 body）或 `200`（有删除结果）

## 5. 分页、排序、过滤（统一接口契约）

- 分页参数（推荐）：
  - `limit`：默认 20，最大 100
  - `cursor`：游标（推荐优于 offset）
- 排序参数：
  - `sort`：例如 `created_at` 或 `-created_at`
- 过滤参数：
  - 简单过滤走 query（如 `status=active`）
  - 复杂过滤走 `POST /resources/search` 或 `POST /resources:query`

## 6. 版本与兼容性

- 若需要版本化，优先使用路径版本：`/api/v1/...`
- 不随意破坏兼容：
  - 新增字段：允许（客户端需容错）
  - 删除/改名字段：视为 breaking change，需要版本升级或迁移期

## 7. 幂等与重试

- 客户端可能重试：写接口需要考虑幂等性
- 如有必要支持幂等键：
  - header：`Idempotency-Key: <uuid>`
  - 服务端存储 key → 结果，确保重复请求返回相同结果

## 9. FastAPI 项目落地建议（与本项目结构配套）

- 路由放在 `src/shopkeeper_kb/app/`（按资源拆分：`items.py`, `documents.py` 等）
- 输入/输出模型用 Pydantic（请求校验、响应契约）
- 依赖注入（DB/客户端）通过 `Depends` 或集中工厂函数提供，避免在路由函数里直接 new client

## 10. 文档与示例

- 每个 endpoint 必须有：
  - 简短 summary
  - 关键参数说明
  - 常见错误码（见 error-handling 规则）
- 提供最小可复制 curl 示例（可写在 README 或接口文档里）
