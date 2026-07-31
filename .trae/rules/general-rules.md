---
alwaysApply: true
---

# 通用规则（Agent 应用项目结构与代码规范）

本规则用于约束本项目的包结构、代码放置位置与工程习惯，目标是：可维护、可扩展、可测试、可部署。

## 1. 项目根目录（必须保持清晰）

- Python 工程以 `pyproject.toml` 为唯一配置中心，依赖与脚本入口统一写在其中
- uv 作为环境与依赖管理工具，锁文件为 `uv.lock`
- 虚拟环境目录统一使用 `.venv/`（不提交）
- 临时/大文件目录（如镜像包、数据卷、说明资料）应放在约定目录并在忽略规则中排除

推荐根目录结构：
```
.
├── pyproject.toml
├── uv.lock
├── README.md
├── src/
│   └── shopkeeper_kb/
└── .gitignore
```

## 2. 包布局（src layout）

- 所有可导入的业务代码必须放在 `src/` 下
- 顶层包名与项目名保持一致：`src/shopkeeper_kb/`
- 禁止把可复用代码散落在根目录或 `tests/` 里

当前项目包根：
- `src/shopkeeper_kb/`：主包

## 3. Agent 应用推荐分层（写代码放哪里）

在 `src/shopkeeper_kb/` 下按职责拆分模块，避免一个文件无限膨胀。

推荐结构（可按实际增删）：
```
src/shopkeeper_kb/
├── __init__.py
├── __main__.py                # 支持 python -m shopkeeper_kb
├── app/                       # 对外应用层（API/服务启动）
│   ├── __init__.py
│   └── api.py                 # FastAPI/路由（如果有 Web 服务）
├── agents/                    # Agent 定义与编排（核心）
│   ├── __init__.py
│   ├── base.py                # Agent 基类/协议
│   └── registry.py            # Agent 注册、选择与路由
├── workflows/                 # 多步流程/状态机（如 LangGraph）
│   ├── __init__.py
│   └── ...
├── prompts/                   # prompt 模板与规范化输入
│   ├── __init__.py
│   ├── system.md
│   └── ...
├── tools/                     # 工具函数（可被 Agent 调用）
│   ├── __init__.py
│   ├── mongo.py               # MongoDB 读写封装（如果用）
│   ├── minio.py               # MinIO 读写封装（如果用）
│   └── ...
├── integrations/              # 第三方集成（HTTP SDK、外部服务）
│   ├── __init__.py
│   └── ...
├── settings.py                # 配置加载（.env/环境变量）
├── logging.py                 # 日志初始化（可选）
└── utils/                     # 通用工具（小而纯）
    ├── __init__.py
    └── ...
```

放置规则：
- Agent 逻辑：只放 `agents/` 与 `workflows/`
- 与外部系统交互：优先放 `tools/` 或 `integrations/`（不要把网络/数据库代码写在 agent 文件里）
- FastAPI 路由与启动：放 `app/`
- 配置：集中在 `settings.py`，通过环境变量与 `.env`（开发）注入，避免硬编码

## 4. 入口规范（如何运行）

- 可执行入口统一走 `pyproject.toml` 的 `[project.scripts]`
- CLI/服务启动应提供一个清晰入口函数，例如 `shopkeeper_kb:main`
- 如果需要支持模块运行，提供 `src/shopkeeper_kb/__main__.py`

示例：
- `uv run shopkeeper-kb`
- `uv run python -m shopkeeper_kb`（有 `__main__.py` 时）

## 5. 依赖规范（uv）

- 运行时依赖写入 `[project.dependencies]`
- 测试/开发工具写入 `[dependency-groups].dev`
- 依赖版本策略：
  - 优先使用兼容范围（`>=` 或 `~=`, 视团队策略）
  - 避免无意义地全量锁死到单一版本，锁定交给 `uv.lock`

常用命令：
- 添加运行时依赖：`uv add <pkg>`
- 添加开发依赖：`uv add --dev <pkg>`
- 同步依赖：`uv sync`

## 6. 代码组织与可维护性

- 一个模块只负责一类职责（Agent、工具、集成、配置各自独立）
- 避免循环依赖：`agents/` 不应反向依赖 `app/`
- 函数/类优先小而清晰，避免超长函数与万能工具模块
- 默认不写无意义注释；需要说明“为什么”时写到 README/设计文档或函数 docstring（按团队习惯）

## 7. 文件与数据约束（防止仓库膨胀）

- 不提交：
  - `.venv/`, `__pycache__/`, `*.pyc`
  - 容器数据卷目录（如 `services/**/data`, `services/**/volumes`）
  - 大体积镜像包（`*.tar`）与临时资料（除非明确要求进版本库）
