---
name: smart-commit
description: 基于项目提交规范自动分析 diff、给出拆分方案，并按 atomic commit 自动创建提交（可 dry-run）。
---

你将作为“提交管家”，把当前工作区变更整理为一组符合项目规范的 atomic commits，并在信息充分时自动完成提交。

严格遵循：`.trae/rules/git-commit-message.md`。

## 0) 运行模式

- 默认：自动执行（给出方案后直接落地提交）
- 若用户在指令中包含 `dry-run`：只输出拆分方案与 commit message，不做任何 `git add/commit`

可选参数（用户在命令后追加即可）：
- `task=<id-or-desc>`：任务标识，用于生成分支名与 trailers（若省略默认 `misc`）
- `scope=<scope>`：影响范围（建议从提交规范的 scope 里选，例如 api/db/workflow/infra/docs/config 等；若省略默认 `infra`）
- `base=<branch>`：基线分支，默认 `main`

## 1) 同步基线并创建分支（必须）

目标：先把 `main` 拉到最新，再从最新 `main` 切出一个新分支开展工作；本命令只创建本地提交，不 push。

1. 解析参数：
   - `base` 缺省为 `main`
   - `task` 缺省为 `misc`
   - `scope` 缺省为 `infra`
2. 记录当前分支名（用于结束后可选切回）：
   - `git rev-parse --abbrev-ref HEAD`
3. 若当前工作区不干净，先将变更暂存到本地缓存（stash），避免拉取基线失败：
   - `git status --porcelain=v1`
   - 若不为空：`git stash push -u -m "smart-commit preflight"`
4. 同步远端基线到本地（禁止 merge commit，必须 fast-forward）：
   - `git fetch origin <base> --prune`
   - `git switch <base>`
   - `git pull --ff-only`
5. 从最新基线切新分支（分支名规则：`agent/<scope>-<task>-<yyyymmdd>`）：
   - 分支名中的 task 需做 slug 化：小写、非字母数字替换为 `-`、连续 `-` 合并
   - `git switch -c agent/<scope>-<task>-<yyyymmdd>`
6. 若第 3 步做过 stash，则在新分支恢复本地变更：
   - `git stash pop`（若冲突，停止并提示人工处理冲突后再继续）

## 2) 采集仓库状态（必须）

1. 获取分支与工作区状态：
   - `git rev-parse --abbrev-ref HEAD`
   - `git status --porcelain=v1`
2. 获取 diff（优先聚焦已暂存，其次未暂存）：
   - `git diff --staged`
   - `git diff`
3. 若存在未跟踪文件，列出清单并判断是否应该提交（生成物/临时文件/敏感文件一律不提交）。

## 3) 生成“原子提交”拆分方案（必须）

按以下原则分组变更，输出一个 commit plan（按顺序）：

- 一个 commit 只做一件事：功能/修复/重构/格式化/依赖升级/文档不得混在同一提交
- 优先按“语义边界”拆分，其次按目录/模块拆分
- 若存在纯格式化或大范围重命名，单独成 commit
- 若存在可能是临时代码/调试代码/生成物/敏感信息，必须指出并从计划中排除

对每个 planned commit，必须产出：

- **Commit ID（临时编号）**：C1/C2/...
- **包含文件**：明确到文件路径
- **目的说明**：一句话解释“为什么需要这个提交”
- **提交信息**：严格按规则文件生成（中文 subject + 英文 type/scope）

## 4) 生成 commit message（必须）

每个 commit 的 message 使用如下结构：

```
<type>(<scope>)!?: <subject>

<body>

Agent-Task: <从上下文推断或由分支名/issue/用户描述提取>
Agent-Decision: <本提交的关键决策与理由，至少一句>
Agent-Model: <可选，若未知可省略>
Agent-Limitation: <可选>
Refs: <可选>
Closes: <可选>
```

规则：

- subject 用动词开头，避免“更新/修改/处理一下/一些改动”
- 若本次变更属于 breaking change，必须加 `!` 并写 `BREAKING CHANGE: ...` 迁移说明

## 5) 自动落地（非 dry-run 必须执行）

按 commit plan 从 C1 到 Cn 依次执行：

1. 确保工作区干净可控：
   - 若上一步提交后仍有 staged 文件，先 `git reset` 回到干净暂存区，再按计划重新 add
2. 仅暂存本 commit 的文件：
   - `git add <files...>`
   - 必须用 `git diff --staged` 复核：只包含本 commit 的语义变更
3. 创建提交：
   - 使用 stdin 方式写入完整多行 message，确保 trailers 连续成块
4. 提交后复核：
   - `git show --name-only --stat --oneline -1`
   - 若发现混入无关变更，必须立即 `git reset --soft HEAD~1` 回退并重新拆分后再提交

重要约束：
- 本命令只做本地提交，不允许 `git push`
- 需要创建 PR 时，使用 `/smart-pr` 再推送到 GitHub

## 6) 输出总结（必须）

- 最终生成的 commits 列表（`git log --oneline -n <N>`）
- 当前工作区是否仍有未提交变更（`git status --porcelain=v1`）
- 若剩余变更无法自动归类，说明原因并给出下一步建议（例如：需要用户确认是否要提交某些文件）
