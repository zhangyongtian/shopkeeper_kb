---
name: review-security
description: 先做代码审查再做安全审计。Invoke when you want a combined review (code-reviewer + security-auditor) before merge/release.
---

请按以下流程一次性完成“代码审查 + 安全审计”，并输出合并后的报告。

## 1) 确定审查范围

- 优先审查“最近变更”：如果仓库存在 Git 历史，先列出最近变更文件与 diff；若无法获取变更历史，则退化为审查 `src/`、`pyproject.toml`、配置文件与脚本入口等核心文件。
- 如用户在对话中明确指定了文件/目录/分支/PR，按用户指定范围为准。

## 2) 运行代码审查（code-reviewer）

- 调用 `code-reviewer` 子智能体审查上述范围内的代码质量与工程最佳实践。
- 关注点：逻辑正确性、可维护性、可读性、边界条件、错误处理、性能、API 设计一致性、与项目结构规范的符合度。
- 产出：按文件与行号定位问题，给出可执行的修改建议（不直接改文件，除非用户明确要求你修改）。

## 3) 运行安全审计（security-auditor）

- 调用 `security-auditor` 子智能体扫描同一范围内的安全风险。
- 重点检查：
  - 明文密钥/Token/密码/连接串
  - 不安全的默认配置（如对外暴露的管理面板、无鉴权数据库、开放端口）
  - 注入风险（SQL/NoSQL/命令注入）、不安全反序列化、XSS/SSRF（如适用）
  - 依赖风险（过宽版本范围/可疑依赖/供应链风险提示）

## 4) 合并输出为一份报告

按以下结构输出（用项目内可点击的 file:/// 链接引用文件与行号）：

1. **Overview**
   - 审查范围（文件/目录/变更集）
   - 总体结论（是否建议合并/上线）

2. **Code Review Findings**
   - 表格：File | Line | Severity | Issue | Suggestion

3. **Security Audit Findings**
   - 风险等级：Critical/High/Medium/Low
   - 每条包含：File + Line + 描述 + 修复建议

4. **Action List**
   - P0（必须修复才能合并/上线）
   - P1（建议尽快修复）
   - P2（可择机优化）

