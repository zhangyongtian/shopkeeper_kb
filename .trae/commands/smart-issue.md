---
name: smart-issue
description: 将需求整理为任务 Issue（支持 Order/Scope/DoD），并返回可用于 smart-pr 的关联参数。
---

你将作为“任务管家”，把用户的需求整理为一个结构化任务 Issue（或复用已有 Issue），用于多智能体协作与顺序合并。

本命令优先面向 GitHub（使用 `gh`），但输出内容必须平台无关：Issue 标题、Order、Scope、DoD、关键词，后续可迁移到其他平台的任务系统。

可选参数（用户在命令后追加即可）：
- `title=<text>`：Issue 标题；若省略，从用户需求生成
- `order=<NNN>`：顺序号（建议 3 位数字，如 001/010）；若省略，提示用户提供或先用 999
- `scope=<scope>`：影响范围（api/db/workflow/agent/tools/infra/docs/config/other）；若省略，自动判断
- `labels=<a,b,c>`：额外标签（可选）

## 1) 拉取现有任务（必须）

1. 检查 `gh` 可用且已登录（若不可用，则退化为：只输出 issue 草稿文本，不创建）：
   - `command -v gh`
   - `gh auth status -h github.com`
2. 列出 open issues（最多 30 条），用于去重与复用：
   - `gh issue list --state open --limit 30 --json number,title,labels,url`

## 2) 生成 Issue 草稿（必须）

从用户需求中提取并生成：

- Title（简短、可检索）
- Order（NNN）
- Scope（一个为主）
- Summary（1–3 句话，描述“为什么/目标/边界”）
- Definition of Done（DoD，必须可验证）
- Risks / Notes（可选）

建议的 Issue body 格式（平台无关）：

```
Order: NNN
Scope: <scope>

Summary:
- ...

Definition of Done:
- [ ] ...
- [ ] ...

Notes:
- ...
```

## 3) 去重/复用逻辑（必须）

对比第 1 步列出的 open issues：
- 若存在标题高度相似且 scope 一致的 Issue，优先建议复用（不要创建重复 Issue）
- 若用户明确要求新建，则创建新 Issue

## 4) 创建 Issue（非 dry-run 必须执行）

若 `gh` 可用：
- `gh issue create --title <title> --body <body> --label task --label <scope> ...`

若 `gh` 不可用：
- 输出可复制的 Title/Body，让用户在任意平台手动创建

## 5) 输出结果（必须）

输出以下内容供后续命令使用：
- Issue 编号与链接（若已创建/复用）
- 推荐的 PR 关联参数（给 smart-pr 用）：
  - `issue=<number>`
  - `order=<NNN>`
  - `task=<slug>`

