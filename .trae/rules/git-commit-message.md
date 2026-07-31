---
alwaysApply: true
scene: git_message
---

你生成的 Git 提交信息必须遵循顶级开源项目常用的 Conventional Commits（与 Angular 规范兼容），目标：可读、可检索、可自动生成版本日志。

提交信息格式：
```
<type>(<scope>): <subject>

<body>

<footer>
```

必须遵守：
- 使用英文提交信息
- 第一行不超过 72 字符（优先 50–72）
- `<subject>` 使用祈使句现在时（imperative），不要以大写字母开头，不要以句号结尾
- `<scope>` 可省略；当改动集中在某个模块/目录/功能时必须填写
- 有破坏性变更时必须包含 `!` 或 `BREAKING CHANGE:`（二选一或同时使用）
- 有关联 Issue/PR 必须在 footer 使用 `Refs:` 或 `Closes:`，例如 `Closes #123`
- body 与 footer 可省略；但当改动非显而易见、涉及行为变化、或需要迁移说明时必须写 body

type 取值（仅限以下，按语义选择最贴切的一个）：
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

scope 建议（示例，不限于此）：
- api, ui, auth, db, infra, docs, deps, config, build, ci

body 写作要求：
- 解释“为什么”而不是重复“做了什么”
- 有行为变化时描述旧行为/新行为以及迁移方式

示例：
- feat(api): add bulk import endpoint
- fix(auth): handle expired refresh token
- refactor(db): extract mongo client factory
- perf(ui): reduce initial bundle size
- build(deps): bump fastapi to 0.141.1
- revert: revert "feat(api): add bulk import endpoint"

破坏性变更示例：
```
feat(api)!: rename /v1/items to /v1/products

BREAKING CHANGE: Clients must migrate to /v1/products.
Closes #456
```
