---
name: smart-branch
description: 自动同步基线并创建/切换到标准命名的工作分支（不提交、不 push）。
---

你将作为“分支管家”，在开始开发前统一完成：同步基线分支到最新、创建标准命名的本地分支，并切换到该分支继续工作。

本命令只负责分支与同步，不做任何提交，也不 push。

可选参数（用户在命令后追加即可）：
- `task=<id-or-desc>`：任务标识，用于分支名（若省略默认 `misc`）
- `scope=<scope>`：影响范围（建议：api/db/workflow/agent/tools/infra/docs/config/other；若省略默认 `infra`）
- `base=<branch>`：基线分支，默认 `main`
- `name=<branch>`：直接指定目标分支名；提供后忽略 task/scope 的自动命名

## 1) 前置检查（必须）

1. 确认存在远端 `origin`：
   - `git remote -v`
2. 若工作区不干净，先 stash（避免拉取/切换失败）：
   - `git status --porcelain=v1`
   - 若不为空：`git stash push -u -m "smart-branch preflight"`

## 2) 同步基线（必须）

1. 同步远端基线到本地（禁止 merge commit，必须 fast-forward）：
   - `git fetch origin <base> --prune`
   - `git switch <base>`
   - `git pull --ff-only`

## 3) 创建或切换分支（必须）

1. 若提供 `name=<branch>`：
   - 若本地分支存在：`git switch <branch>` 并尝试 `git pull --ff-only`
   - 若不存在：从最新基线创建：`git switch -c <branch>`
2. 若未提供 `name`：按规则生成分支名并创建：
   - 分支名：`agent/<scope>-<task>-<yyyymmdd>`
   - task 需做 slug 化：小写、非字母数字替换为 `-`、连续 `-` 合并
   - 若分支已存在，自动追加 `-2`、`-3` 直到可用
   - `git switch -c <branch>`

## 4) 恢复 stash（如有）

- 若第 1 步做过 stash，则执行 `git stash pop`
- 若出现冲突，停止并提示人工处理冲突后再继续开发

## 5) 输出总结（必须）

- 当前分支名
- 是否执行过 stash
- 下一步建议：在当前分支完成修改后运行 `/smart-commit` 生成本地提交，再用 `/smart-pr` 推送并创建 PR

