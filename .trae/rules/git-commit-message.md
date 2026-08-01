---
alwaysApply: true
scene: git_message
---

本规则用于生成可维护、可追溯、可审查的 Git 提交信息（Commit Message）。参考 Conventional Commits（Angular 兼容）并结合 AI/Agent 开发的常见痛点，目标是让每个提交不仅能看出 diff，还能看懂意图、决策与影响范围，便于 code review、回滚与 bisect。

**核心原则（先做对，再写好）**
- 原子提交：一个 commit 只表达一个可解释、可回滚、可验证的语义变化；不要把功能、重构、格式化、依赖升级混在一起
- 避免两种极端：不要做“巨型单一 commit”，也不要做“无意义碎片 commit”（如 fix typo / try again / update file）
- 保持工作区干净：提交前只暂存（stage）与本意图相关的文件；生成物、临时调试、无关格式化变更不得混入
- 严禁提交敏感信息：API Key、密码、Token、私钥、连接串等不得进入历史（含提交信息与 trailer）

**提交信息格式（推荐）**
```
<type>(<scope>)!?: <subject>

<body>

<trailers>
```

**1) Header（第一行）**
- 第一行不超过 72 字符（优先 50–72）
- `<type>`、`<scope>` 必须使用英文小写（便于工具生态与检索），`<subject>` 建议用中文表达意图（若对外开源可改为英文）
- `<subject>` 用动词开头，表达“做什么”，避免流水账与无主语描述
  - 推荐：`新增...`、`修复...`、`移除...`、`重命名...`、`调整...`、`优化...`、`限制...`
  - 避免：`更新`、`修改`、`处理一下`、`一些改动`、`final`、`try again`
- `<scope>` 可省略；当改动集中在某个模块/目录/功能时必须填写

**2) Body（正文，可选但强烈建议）**
- 写“为什么/背景/约束/权衡”，不要重复“改了哪些文件”
- 有行为变化时必须写清：旧行为 → 新行为、迁移方式、兼容性说明
- 可包含简短的“Review 指引”：建议 reviewer 重点看哪里

**3) Trailers（页脚/尾注，结构化键值对，强烈建议）**
Trailer 是 Git 原生支持的结构化键值对（位于 message 末尾，且与正文之间空一行），便于机器检索与后续追溯。

通用 trailers（按需使用）：
- `Refs: #123`：关联但不关闭 issue
- `Closes: #123`：关闭 issue
- `Co-authored-by: Name <email>`：共同作者

AI/Agent 场景建议 trailers（当提交由 AI/Agent 生成或强参与时使用）：
- `Agent-Task: <任务描述或任务 ID>`（必填，越具体越好）
- `Agent-Decision: <关键设计决策及理由>`（必填，回答“为什么这样做”）
- `Agent-Model: <模型名称>`（可选）
- `Agent-Limitation: <已知局限/后续 TODO>`（可选）

禁止在 trailers 中写入：
- prompt 原文中可能包含的敏感信息（token、连接串、用户隐私等）
- 无意义的自动化噪声（如 Generated-by: xxx 但无法用于排查）

**破坏性变更（Breaking Change）**
- 有破坏性变更时必须使用 `!` 或 `BREAKING CHANGE:`（建议两者同时使用）
- `BREAKING CHANGE:` 必须描述迁移方式（客户端/调用方需要怎么改）

**type 取值（仅限以下，按语义选择最贴切的一个）**
- feat: 新增功能（对用户可见的能力变化）
- fix: 修复缺陷/bug
- docs: 仅文档变更
- style: 仅格式/排版（不影响逻辑），例如空格、分号、lint 修复
- refactor: 重构（不修 bug、不加功能）
- perf: 性能优化
- test: 新增/调整测试
- build: 构建系统或依赖变更（如 npm/pip/ci 构建）
- ci: CI 配置或脚本变更
- chore: 杂项维护（不属于以上分类）
- revert: 回滚提交

**scope 建议（示例，不限于此）**
- api, ui, auth, db, infra, docs, deps, config, build, ci
- agent, workflow, tools, import, search

**长任务的提交切分（Checkpoint + 最终整理）**
- 长任务必须“小步提交”，在关键节点做 checkpoint（例如：接口/模型定义、核心逻辑完成、配置接入完成）
- checkpoint 允许使用临时标记，但在合并前必须整理历史
  - 推荐：`chore(wip): <阶段性说明>`
- 开 PR 前使用 interactive rebase 把 checkpoint 整理为少量语义清晰的原子提交（squash/fixup/reword）

**提交前自检清单（用于消灭常见问题）**
- 只提交相关内容：`git diff --staged` 没有无关格式化/生成物/调试代码
- 不提交敏感信息：确认代码与提交信息中无 key/token/密码/连接串
- 不做混合提交：功能与重构/依赖升级拆分为不同 commit
- message 可读可检索：header 清晰、body 写清“为什么”、必要 trailers 齐全

**示例**
功能提交（含 Agent trailers）：
```
feat(auth): 新增刷新令牌轮换机制

减少频繁重新登录，同时保持会话安全；刷新令牌存储在 httpOnly cookie 以降低 XSS 风险。

Agent-Task: PROJ-234 - 为鉴权服务增加 refresh token 支持
Agent-Decision: 采用 7 天滑动窗口而非固定过期时间，以平衡 UX 与安全性
Agent-Model: gpt-4o
Agent-Limitation: 登出场景下 Redis TTL 尚未与 token 失效对齐
Refs: #234
```

破坏性变更：
```
feat(api)!: 重命名 items 接口为 products

BREAKING CHANGE: 客户端需将 /v1/items 迁移为 /v1/products。
Closes: #456
```
