# CodeReview

> AI is good at making code work. It is not always good at knowing when to stop writing code.

CodeReview evaluates whether a code change introduces more **implementation overhead** than the task actually required.

[English](#features) | [中文文档](#功能)

## Problem

Modern AI coding assistants can produce working code, but they often introduce extra complexity by:

- changing 10+ files when 2-3 would solve the task
- adding 1000+ lines when 100-200 would be enough
- creating unnecessary classes, managers, handlers, and factories
- introducing pass-through layers that add no value
- duplicating existing capabilities
- drifting beyond the original task scope

The result is code that works, but is harder to debug, maintain, and review.

## Features

- **Change Size Analysis**: Detects when a change is larger than necessary
- **Complexity Delta**: Measures how much complexity increased vs. decreased
- **One-use Abstraction Detection**: Finds classes with no state, single method, single caller
- **Pass-through Detection**: Identifies layers that only forward calls
- **Duplicate Capability Detection**: Finds reimplemented existing functions; for HIGH-confidence pairs, compares parameter signatures to determine whether they can be merged into a shared helper (`mergeable`, `merge_reason` in JSON)
- **Scope Drift Detection**: Identifies files unrelated to the stated task; with LLM enabled, returns per-file similarity scores and matched keywords
- **Top Complexity Functions**: Lists the most complex functions after the change, flagging those over threshold (complexity > 20)
- **Deleted-file Accounting**: Includes deleted Python files in the complexity delta
- **Explainable Scoring**: 0-100 score with clear breakdown
- **Explicit `--cwd`**: Run against any repository, not just the current directory

## Installation

```bash
pip install codereview
```

Or install from source:

```bash
git clone <repo-url>
cd codereview
pip install -e .
```

## Quick Start

```bash
# Review current branch against main
codereview review --base main --task "Add user permission check"

# Review a repository directory
codereview review --base main --task "Add user permission check" --cwd /path/to/repo

# Output JSON
codereview review --base main --task "Add user permission check" --json
```

## Example

```bash
$ codereview review --base main --task "Fix SSE error parsing"

CodeReview Report
==================================================

Task
Fix SSE error parsing

Base
main

Change Summary
--------------------------------------------------
Files Changed:       3
Lines Added:         45
Lines Deleted:       5

New Functions:       2
New Classes:         0

Change Size Risk:
LOW

Complexity Delta
--------------------------------------------------
Before:              12
After:               18
Delta:               +6 (+50.0%)

Risk:
MEDIUM

Implementation Overhead
--------------------------------------------------
Score: 18 / 100
Risk: LOW
```

## How It Works

1. **Git Diff Analysis**: Collects changed files, added/deleted lines, and diff context
2. **Static Analysis**: Analyzes before/after code using Python's `ast` module
3. **Detection**: Applies deterministic rules to identify suspicious patterns
4. **Scoring**: Computes explainable 0-100 score based on weighted heuristics
5. **Optional LLM Review**: Adds semantic analysis for scope drift and duplicate detection

## Scoring

| Dimension | Weight | What It Measures |
|-----------|--------|------------------|
| Change Size | 20 | Number of files changed, lines added |
| Complexity Delta | 30 | Increase in complexity from before to after |
| Abstraction | 20 | One-use classes, pass-through layers |
| Duplicated Logic | 15 | Reimplementation of existing capabilities |
| Scope Drift | 15 | Files unrelated to the task |

**Risk Levels:**
- 0-29: Low
- 30-59: Medium
- 60-79: High
- 80-100: Very High

## LLM Configuration (Optional)

Set these environment variables to enable semantic review:

```bash
export CODEREVIEW_API_KEY="your-api-key"
export CODEREVIEW_BASE_URL="https://api.openai.com/v1"  # or your endpoint
export CODEREVIEW_MODEL="gpt-4o-mini"  # or your model
```

Without LLM configuration, CodeReview still runs all static analysis.

## GitHub Actions

`codereview` can be used in CI to evaluate implementation overhead on PRs. Example:

```yaml
- name: Run CodeReview
  uses: ./.github/actions/codereview
  with:
    base: main
    task: "${{ github.event.pull_request.title }}"
    token: "${{ secrets.GITHUB_TOKEN }}"
```

## Limitations

- **Python only** (MVP)
- Requires a Git repository
- Optional LLM features require API access
- Not a bug scanner — focuses on implementation overhead

## Roadmap

- [x] Top-N complexity localization (functions over threshold flagged)
- [x] Duplicate mergeability hints (parameter-signature comparison for HIGH-confidence pairs)
- [x] Explainable scope drift (per-file similarity scores and matched keywords)
- [ ] Multi-language support (JavaScript, TypeScript, Java, etc.)
- [ ] VS Code extension
- [ ] Web dashboard
- [ ] Automatic refactoring suggestions
- [ ] Team analytics

## Contributing

CodeReview follows KISS principles. Before submitting code, ask:

1. Is this change necessary for MVP?
2. Does it introduce unnecessary complexity?
3. Can it be implemented with fewer lines?
4. Is it well tested?

## License

MIT

---

# CodeReview（中文）

> AI 擅长让代码跑起来，但不太擅长知道什么时候该停笔。

CodeReview 评估一次代码修改是否引入了超出任务实际需要的**实现开销**（implementation overhead）。

## 问题

现代 AI 编程助手能产出可运行的代码，但往往以以下方式带来额外复杂度：

- 2-3 个文件就能解决，却改了 10+ 个
- 100-200 行足够，却加了 1000+ 行
- 造出不必要的 class、manager、handler、factory
- 引入没有价值的透传层
- 重复实现已有能力
- 偏离原始任务范围

代码虽然能跑，但更难调试、维护和 review。

## 功能

- **变更规模分析**：检测修改是否超出必要范围
- **复杂度增量**：衡量修改前后复杂度的增减
- **一次性抽象检测**：找出无状态、单方法、单调用者的类
- **透传检测**：识别只做转发、无附加价值的层
- **重复能力检测**：找出重复实现的已有函数；对高置信度重复对，比较参数签名判断能否合并为共享函数（JSON 输出含 `mergeable`、`merge_reason`）
- **范围漂移检测**：识别与任务无关的文件；启用 LLM 后返回每个文件的相似度分数和匹配关键词
- **Top 复杂度函数**：列出修改后最复杂的函数，标记超过阈值（复杂度 > 20）的
- **删除文件统计**：复杂度增量包含被删除的 Python 文件
- **可解释评分**：0-100 分，带清晰的分项拆解
- **显式 `--cwd`**：可对任意仓库目录运行，不限于当前目录

## 安装

```bash
pip install codereview
```

或从源码安装：

```bash
git clone <repo-url>
cd codereview
pip install -e .
```

## 快速开始

```bash
# 对当前分支与 main 做审查
codereview review --base main --task "Add user permission check"

# 审查指定仓库目录
codereview review --base main --task "Add user permission check" --cwd /path/to/repo

# 输出 JSON
codereview review --base main --task "Add user permission check" --json
```

## 示例

```bash
$ codereview review --base main --task "Fix SSE error parsing"

CodeReview Report
==================================================

Task
Fix SSE error parsing

Base
main

Change Summary
--------------------------------------------------
Files Changed:       3
Lines Added:         45
Lines Deleted:       5

New Functions:       2
New Classes:         0

Change Size Risk:
LOW

Complexity Delta
--------------------------------------------------
Before:              12
After:               18
Delta:               +6 (+50.0%)

Risk:
MEDIUM

Implementation Overhead
--------------------------------------------------
Score: 18 / 100
Risk: LOW
```

## 工作原理

1. **Git Diff 分析**：收集变更文件、增删行数、diff 上下文
2. **静态分析**：用 Python `ast` 模块分析修改前后的代码
3. **检测**：应用确定性规则找出可疑模式
4. **评分**：基于加权启发式计算可解释的 0-100 分
5. **可选 LLM 审查**：对范围漂移和重复检测做语义分析

## 评分

| 维度 | 权重 | 衡量内容 |
|------|------|----------|
| 变更规模 | 20 | 变更文件数、新增行数 |
| 复杂度增量 | 30 | 修改前后复杂度差值 |
| 抽象 | 20 | 一次性类、透传层 |
| 重复逻辑 | 15 | 重复实现的已有能力 |
| 范围漂移 | 15 | 与任务无关的文件 |

**风险等级：**
- 0-29：低
- 30-59：中
- 60-79：高
- 80-100：非常高

## LLM 配置（可选）

设置以下环境变量启用语义审查：

```bash
export CODEREVIEW_API_KEY="your-api-key"
export CODEREVIEW_BASE_URL="https://api.openai.com/v1"  # 或你的端点
export CODEREVIEW_MODEL="gpt-4o-mini"  # 或你的模型
```

不配置 LLM 时，CodeReview 仍会运行所有静态分析。

## GitHub Actions

`codereview` 可在 CI 中对 PR 做实现开销检查。示例：

```yaml
- name: Run CodeReview
  uses: ./.github/actions/codereview
  with:
    base: main
    task: "${{ github.event.pull_request.title }}"
    token: "${{ secrets.GITHUB_TOKEN }}"
```

## 限制

- **仅支持 Python**（MVP）
- 需要 Git 仓库
- LLM 功能可选，需要 API 访问权限
- 不是 bug 扫描器——专注于实现开销

## 路线图

- [x] Top-N 复杂度定位（标记超阈值函数）
- [x] 重复合并提示（对高置信度重复对比较参数签名）
- [x] 可解释范围漂移（每文件相似度分数 + 匹配关键词）
- [ ] 多语言支持（JavaScript、TypeScript、Java 等）
- [ ] VS Code 扩展
- [ ] Web 仪表盘
- [ ] 自动重构建议
- [ ] 团队分析

## 贡献

CodeReview 遵循 KISS 原则。提交代码前请自问：

1. 这个改动对 MVP 是必要的吗？
2. 是否引入了不必要的复杂度？
3. 能否用更少的行数实现？
4. 是否有充分测试？

## 许可证

MIT
