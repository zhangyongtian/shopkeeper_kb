---
alwaysApply: true
scene: vcs_workflow
---

本规则定义一套平台无关的“任务（Issue）驱动协作 + 顺序合并”工作流。目标：支持多个智能体并行开发，同时保证合并进入主干的顺序可控、可追溯、可审查。

## 1) 任务（Issue）作为单一入口

- 每个任务必须对应一个 Issue（或任意平台上等价的任务单元）
- 一个 Issue 只做一件事（与 atomic commit 原则一致）
- Issue 必须包含以下字段：
  - `Order: NNN`：三位数字顺序号（001/010/120），决定合并顺序
  - `Scope: <scope>`：影响范围（api/db/workflow/infra/docs 等）
  - `Definition of Done`：可验证的验收标准

## 2) 分支与 PR/MR 约定

- 分支命名：`agent/issue-<id>-<slug>` 或 `agent/<order>-<slug>`
- 每个任务最多一个活跃 PR/MR；不要在同一分支串行做多个不相关任务
- PR/MR 必须关联任务：
  - 在 PR/MR 描述中写明：
    - `Order: NNN`
    - `Task: <issue-id-or-link>`
  - 若平台支持自动关闭任务：在描述末尾追加 `Closes: #<issue>`

## 3) 提交规范（与本规则配套）

- commit message 必须遵循：`.trae/rules/git-commit-message.md`
- PR/MR 合并前，必须确保提交历史已整理为语义清晰的 atomic commits（必要时使用 rebase/squash）

## 4) 顺序合并（核心）

- 同一目标分支（如 main）在任意时刻只能有一个任务进入“合并执行”阶段
- 合并顺序以 `Order: NNN` 为准，从小到大
- 合并动作必须满足：
  - 分支已与最新主干同步（或合并系统能基于最新主干验证）
  - CI/检查通过（若启用）
  - 无敏感信息进入仓库

## 5) 平台适配（实现层）

本规则只定义“应该怎样做”，不绑定具体平台。具体实现可按平台选择：

- GitHub：Issue + PR + Labels + Actions/合并队列
- GitLab：Issue + MR + Labels + CI/合并队列
- 自建平台：用等价的任务单元与合并脚本实现相同语义

最低要求：无论用哪个平台，PR/MR 描述里必须有 `Order:` 与 `Task:`，这样队列与自动化才能跨平台复用。

