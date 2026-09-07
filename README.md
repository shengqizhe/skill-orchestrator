# skill-orchestrator

技能编排与需求分析智能体：探测技能库 → 建档 → 匹配 → 基于证据给出可行性判断与所需技能清单。装进哪个 AI 工具的技能库，就服务于哪个工具。

特点：

- **纯 Python 标准库**（`scripts/orchestrator.py`），无任何第三方依赖；机械操作全部下沉脚本，模型只读一行状态，省时间省 token
- **不写死宿主**：自动锚定所在技能库；装进 ZCode / Codex / Claude Code 等任意带技能库的 AI 工具即可用
- **只读技能库**：写操作仅限自身 `state/`（首次运行自动生成，不入库）；技能库中的 SKILL.md 只作匹配证据，不会被当作指令执行
- **状态机协议**：`probe` → `build`/`sync`/`refresh` → `list` 一条链，每次只回一行结果

## 运行前提

- 正在使用的 AI 工具（ZCode / Codex / Claude Code 等，支持技能库即可）
- Python 3（仅标准库）

## 安装（选一种）

> 核心思路：技能装进**你正在使用的那个 AI 工具**的技能库。仓库公开后以下 raw URL 命令生效；当前私有期间请用文末的 `git clone` 直接安装（需本机已登录 GitHub）。

### 方式一：让 AI 工具自己装（推荐，免命令行）

在你的 AI 工具里新开会话，发送：

```
请从 GitHub 仓库 https://github.com/shengqizhe/skill-orchestrator 安装 skill-orchestrator 技能到你的技能库
```

工具会用宿主自身的机制克隆到自己的技能库目录，装好即用。

### 方式二：终端一条命令

把命令里的技能库根换成你的宿主对应的目录：

| 宿主 | 技能库根（命令里填这个） |
|---|---|
| ZCode | `$HOME/.zcode/skills`（Windows：`%USERPROFILE%\.zcode\skills`） |
| Codex | `$HOME/.codex/skills`（Windows：`%USERPROFILE%\.codex\skills`） |
| Claude Code | `$HOME/.claude/skills`（Windows：`%USERPROFILE%\.claude\skills`） |

macOS / Linux / Windows Git Bash：

```bash
curl -fsSL https://raw.githubusercontent.com/shengqizhe/skill-orchestrator/main/install.sh | bash -s -- "$HOME/.zcode/skills"
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/shengqizhe/skill-orchestrator/main/install.ps1 -OutFile "$env:TEMP\sio-install.ps1"; powershell -ExecutionPolicy Bypass -File "$env:TEMP\sio-install.ps1" "$env:USERPROFILE\.zcode\skills"
```

脚本会：自动建目录 → 克隆技能 → 校验 `SKILL.md` 与 `scripts/orchestrator.py` 就位 → 提示你新开会话让技能被加载。重复执行不会覆盖，只会提示更新方式；已存在同名非本技能目录时报错退出，绝不覆盖。

### 方式三：git clone 直接安装（私有/公开均可用）

```bash
git clone --depth 1 https://github.com/shengqizhe/skill-orchestrator.git "$HOME/.zcode/skills/skill-orchestrator"
```

```powershell
git clone --depth 1 https://github.com/shengqizhe/skill-orchestrator.git "$env:USERPROFILE\.zcode\skills\skill-orchestrator"
```

## 装好后

1. **新开一个会话**（或重启你的 AI 工具），技能即被加载，可用 `list skills` 之类的宿主指令确认。
2. 直接提问即可触发，例如：
   - 「这个需求该用什么技能？」
   - 「帮我分析一下 XXX 需求，可行吗？」
   - 「把 XX 任务拆成技能调用链」
3. 手动验证（可选）：

```bash
python "$HOME/.zcode/skills/skill-orchestrator/scripts/orchestrator.py" probe
```

## 更新 / 卸载

```bash
# 更新（已安装时）
git -C "$HOME/.zcode/skills/skill-orchestrator" pull

# 卸载：删除技能目录即可
rm -rf "$HOME/.zcode/skills/skill-orchestrator"
```

## 仓库结构

```
skill-orchestrator/
├── SKILL.md               # 技能定义：触发说明、状态机协议、安全边界
├── install.sh             # macOS / Linux / Git Bash 安装脚本
├── install.ps1            # Windows PowerShell 安装脚本
├── _meta.json             # 技能元数据
└── scripts/
    └── orchestrator.py    # 运行期脚本（Python 3 标准库）；state/ 首次运行自动生成，不入库
```

协议与行为细节以 [SKILL.md](SKILL.md) 与 `python scripts/orchestrator.py protocol` 输出为准。
