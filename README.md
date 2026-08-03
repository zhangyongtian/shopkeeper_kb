# 作手式盘面多模态复盘助手（shopkeeper-kb）

面向学习与复盘的多模态交易研究助手：支持导入交易类专业文档（PDF/Markdown）与盘面图片（K 线/指标/结构图），输出结构化解读与可追溯证据引用，并以风险约束为核心组织输出（非投资建议）。

### 适用场景

- 盘面复盘：对 K 线/指标截图输出结构化观察、解释与风险约束
- 交易学习：对概念、形态、仓位与风控进行“规则 + 证据引用”的研究式问答
- 文档索引：将 PDF/Markdown 解析为可检索的结构化内容与图文关联素材

### 能力概览

- 文档导入流水线：PDF/Markdown 导入、结构化解析、切片与元数据提取（持续完善）
- PDF 结构化解析：集成 MinerU，支持超页自动切分、分卷并发解析、断点续传下载与产物合并
- Markdown 图片抽取：解析图片相对路径并回填绝对路径，抽取图片前后文用于多模态理解
- 研究式问答输出：面向“概念解释 / SOP / 诊断式问答”的结构化输出与证据引用（持续完善）
- 可观测性：注入并回传 `X-Request-Id`，便于日志关联排障
- 统一错误响应：非 2xx 统一返回 `{ "error": { "code", "message", "details", "request_id" } }`

### 专家级输出协议（非投资建议）

面向盘面截图/图表的输出结构固定为：

- Observation：图上事实（趋势、关键位、形态、量价关系）
- Interpretation：在适用条件约束下给出解释（明确情景与不确定性）
- Risk Plan：风险预算、止损原则、仓位约束与回撤控制（不输出确定性买卖指令）
- Next Check：下一步观察条件与验证信号（用于训练与复盘）
- Evidence：引用具体章节/片段与相关图示（可追溯）

### 工作流概览

```text
PDF/MD 文档
  -> 结构化解析（含超页切分、并发、断点续传）
  -> 合并产物（Markdown + images/part_xxx）
  -> 图片绝对路径 + 前后文抽取（多模态理解输入）
  -> 检索 / 复盘问答（结构化输出 + 证据引用）
```

### 知识库底座（4 本核心 + 1 本补充）

为覆盖技术分析、交易心理、风险管理三大模块，并保证体系完整性，规划引入以下经典书目作为“底座知识库”（用于概念定义、适用条件、反例与风险提示）：

- 技术分析总纲：《金融市场技术分析》（John J. Murphy）：趋势、形态、量价、指标、周期的通用框架
- 蜡烛图与形态：《日本蜡烛图技术》（Steve Nison）：把 K 线形态系统化，适配“读图→解释”的多模态场景
- 交易心理：《交易心理分析》（Mark Douglas）：纪律、执行、偏差与训练方法，支撑“行为诊断式问答”
- 风险管理与系统框架：《通向金融王国的自由之路》（Van K. Tharp）：仓位、止损、回撤与系统评估的规则化框架
- 补充视角（可选）：《金融怪杰》（Jack D. Schwager）：多流派方法论对照，降低单一体系过拟合

镜像/部署说明：

- 项目会提供资料目录约定与导入脚本，支持在镜像中预置或在部署时挂载资料目录，实现开箱即用的“书库 + 多模态复盘”体验
- 请在实际分发与部署时确保你对相关资料拥有合法来源与使用授权

### 资料获取与复现

为避免在公开仓库中传播可能受版权保护的内容，本仓库不在 README 中提供任何书籍资料的直链或提取码。

复现方式：

- 通过合法渠道获取你拥有使用授权的资料（购买正版/作者或出版社授权/公开授权资料）
- 将资料放入 `${DOC_DIR}`（例如 `${DOC_DIR}/finance_books/`）
- 运行导入流程后，产物会输出到 `${OUTPUT_DOC_DIR}`

### 项目结构

```text
src/shopkeeper_kb/
  app/                 FastAPI 应用层（路由/中间件/异常处理）
  workflows/           节点与流程编排
  agents/              运行器与编排入口
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

关键配置项（完整说明见 `.env.example` 注解）：

- `API_HOST` / `API_PORT`：服务监听地址与端口
- `LOG_LEVEL`：日志级别（INFO/DEBUG/ERROR 等）
- `MONGO_URI` / `MONGO_DB`：MongoDB 连接与库名
- `DOC_DIR` / `DOWNLOAD_DIR` / `OUTPUT_DOC_DIR`：本地文档、下载缓存、导入产物目录
- `MINERU_*`：页数限制、切分大小、并发数等 MinerU 解析配置
- `MD_IMG_CONTEXT_CHARS`：图片上下文抽取长度（字符数）

### 快速开始（本地）

```bash
/home/roott/.local/bin/uv sync
cp .env.example .env
/home/roott/.local/bin/uv run shopkeeper-kb
```

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

```python
from shopkeeper_kb import logging_config as log

log.info("message")
log.error("message")
```
