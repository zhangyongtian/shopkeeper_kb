---
name: smart-merge
description: 自动合并 PR 并同步本地 main（可按标题关键词或编号选择 PR）。
---

你将作为“合并管家”，自动选择一个 PR 进行合并，并在合并后同步本地代码。

默认行为：
- 未指定 PR：优先合并最新更新的、标记了 `automerge` 标签的 PR；若不存在则合并最新更新的 open PR
- 指定 PR：优先按 `pr=<number>`；否则按 `q=<keyword>` 在 PR 标题中匹配

可选参数（用户在命令后追加即可）：
- `pr=<number>`：指定 PR 编号（优先级最高）
- `q=<keyword>`：按标题关键词匹配 PR（不区分大小写）
- `base=<branch>`：目标分支，默认 `main`
- `method=merge|squash|rebase`：合并方式，默认 `merge`
- `pull`：合并后同步本地 main（默认启用）

## 1) 前置检查（必须）

1. 检查 `gh` 可用且已登录：
   - `command -v gh`
   - `gh auth status -h github.com`
2. 确认存在 `origin`：
   - `git remote -v`
3. 确认当前工作区干净：
   - `git status --porcelain=v1`

若工作区不干净，停止并提示先运行 `/smart-commit` 或手动处理未提交变更。

## 2) 选择 PR（必须）

1. 拉取 open PR 列表（最多 50 条）：
   - `gh pr list --state open --base <base> --limit 50 --json number,title,updatedAt,isDraft,mergeStateStatus,labels,url`
2. 选择规则：
   - 若提供 `pr=<number>`：直接选该 PR
   - 否则若提供 `q=<keyword>`：在 title 中模糊匹配，若多条命中，选择 updatedAt 最新的一条
   - 否则：优先选择带 `automerge` 标签的 PR 中 updatedAt 最新的一条；若不存在则选择所有 open PR 中 updatedAt 最新的一条

必须跳过 draft PR（`isDraft=true`）。

## 3) 合并策略（必须）

1. 合并前检查 PR 状态：
   - 若 `mergeStateStatus=CLEAN`：尝试直接合并
   - 否则：不要强行合并，改为开启 GitHub Auto-merge（让平台在检查通过后自动合并）
2. 合并命令（按 `method`）：
   - merge：`gh pr merge <pr> --merge --delete-branch`
   - squash：`gh pr merge <pr> --squash --delete-branch`
   - rebase：`gh pr merge <pr> --rebase --delete-branch`
3. Auto-merge 命令（按 `method`）：
   - merge：`gh pr merge <pr> --auto --merge --delete-branch`
   - squash：`gh pr merge <pr> --auto --squash --delete-branch`
   - rebase：`gh pr merge <pr> --auto --rebase --delete-branch`

若仓库策略要求审批或检查未通过，不要绕过规则；只输出当前阻塞条件。

## 4) 合并后同步本地（默认执行）

1. 同步目标分支：
   - `git fetch origin <base> --prune`
   - `git switch <base>`
   - `git pull --ff-only`
2. 若当前不在 `<base>` 分支，切回原分支或保持在 `<base>`，由用户选择（默认保持在 `<base>`）。

## 5) 输出总结（必须）

- 选择的 PR：编号、标题、链接
- 合并方式：merge/squash/rebase
- 合并结果：已合并 / 已开启 auto-merge / 被规则阻塞（说明原因）
- 本地同步结果：当前分支与 `git log -1 --oneline`

