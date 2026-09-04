# fixtures — parser 回归锁

`verify` 子命令用本目录断言 [scripts/orchestrator.py](../orchestrator.py) 的
frontmatter 子集解析器行为。任何会改变解析结果的改动（解析逻辑、`DESC_LIMIT`
截断、默认回退）都会让 `verify` 失败——这是有意为之：改动必须同步更新
`expected.json` 与本文档，而不是悄悄漂移。

## 目录结构

- `skills/<case>/SKILL.md` —— 被测样本
- `expected.json` —— 冻结的期望解析结果（golden output）
- `expected.json` 由真实运行 `parse_skill_dir` 冻结，逐条人工复核后入库

## 样本来源（真实技能库，2026-09 采集）

除注明外，frontmatter **逐字照抄**真实 SKILL.md；正文在首个标题后截断
（解析器只读 frontmatter，正文不影响结果）。

| case | 来源 | 锁住的解析形态 |
|---|---|---|
| `inline-unicode` | `leader/SKILL.md` | 单行中文行内 description；`「」≤·` 等字符 |
| `inline-english` | `ui-ux-pro-max/SKILL.md` | 单行英文长 description（>240 截断） |
| `block-literal` | `file-summary/SKILL.md` | `description: \|` 块标量（literal，含 emoji/中英触发词） |
| `block-folded` | `storage-analyzer/SKILL.md` | `description: >` 折叠块（长文本 240 截断锁） |
| `block-strip` | `neat-freak/SKILL.md` | `>-` 去尾换行符变体 + 块后紧跟 `compatibility:`/嵌套 `metadata:`（锁块边界） |
| `extra-keys` | `aihot/SKILL.md` | 行内 desc + `license` + 嵌套 `metadata`（锁无关键跳过） |
| `degraded` | `references/SKILL.md` | 真实损坏条目：`description: a` 等无意义短值 |
| `no-name` | 派生（document-pro 删 `name:` 行） | 缺 `name` 回退文件夹名 |
| `frontmatterless` | 派生 | 无 frontmatter → 文件夹名 + `(no description)` |

## 解析契约（subset，非全量 YAML）

- frontmatter 必须在文件头部：`---` 开行、`---` 收行（首闭为准）。
- 顶层键必须在第 0 列；只读 `name`/`description`，其余键（`license`、
  `metadata`、`version`…）跳过。
- `description` 支持：行内 plain/引号、换行续接到后续缩进行（plain
  folding）、块标量 `|`/`>`（含 `|+` `|-` `>+` `>-`）。
- 块/折叠/行内最终统一归一化为单个空格（索引只服务触发匹配，不需要
  保留换行/段落）。
- 同名键后者覆盖；无 `name` 用文件夹名；无/空 description →
  `(no description)`；`SKILL.md` 不可读 → `(unreadable)`。

## 明确不支持（有意拒绝，遇到请补样本或升级方案）

带转义的引号、嵌套映射/列表、flow 标量、块标量内注释。当前生态样本未出现；
如果新装技能出现新写法导致解析错读，**先补 fixtures 样本再决定**：接受该写法
（改解析器 + 更新 expected）或继续拒绝（在 SKILL.md 记录）。

## 更新流程

改了解析行为后：跑 `python scripts/orchestrator.py verify` 确认失败点 → 更新
`expected.json`（重新冻结并人工复核）→ 改本表 → 再 `verify` 通过 → 提交。
