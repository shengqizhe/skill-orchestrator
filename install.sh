#!/usr/bin/env bash
#
# skill-orchestrator 安装脚本 (macOS / Linux / Windows Git Bash)
#
# 用法: 把技能装进「你正在使用的 AI 工具」的技能库 —— 第一个参数 = 技能库根目录。
#   方式一(推荐, 免命令行): 把 README 里的安装指令发给你的 AI 工具,
#     它用宿主自身的机制克隆到自己的技能库, 不需要本脚本。
#   方式二(终端一条命令, 仓库公开后可用):
#     curl -fsSL https://raw.githubusercontent.com/shengqizhe/skill-orchestrator/main/install.sh \
#       | bash -s -- "$HOME/.zcode/skills"
#   不传参数时: 若默认的 ZCode 技能库 ($HOME/.zcode/skills) 已存在则装到那里;
#     否则报错提示显式传参 (不擅自建目录、不做多宿主探测)。
#   其他宿主请显式传参: Codex 用 ~/.codex/skills, Claude Code 用 ~/.claude/skills。
#
# 环境变量 SKILL_ORCHESTRATOR_REPO_URL 可覆盖仓库地址 (测试/镜像场景)。
set -euo pipefail

REPO_URL="${SKILL_ORCHESTRATOR_REPO_URL:-https://github.com/shengqizhe/skill-orchestrator.git}"
SKILL_NAME="skill-orchestrator"
DEFAULT_ROOT="$HOME/.zcode/skills"

ROOT="${1:-}"
if [[ -z "$ROOT" ]]; then
  if [[ -d "$DEFAULT_ROOT" ]]; then
    ROOT="$DEFAULT_ROOT"
  else
    cat >&2 <<EOF
用法: install.sh [技能库根目录]

把技能装进「你正在使用的 AI 工具」的技能库:
  ZCode:        $DEFAULT_ROOT
  Codex:        \$HOME/.codex/skills
  Claude Code:  \$HOME/.claude/skills

本机未发现默认的 ZCode 技能库 ($DEFAULT_ROOT),
请显式传入你的技能库根目录, 例如:
  curl -fsSL <本脚本URL> | bash -s -- "\$HOME/.codex/skills"
EOF
    exit 2
  fi
fi

ROOT="${ROOT%/}"
TARGET="$ROOT/$SKILL_NAME"

# 已有安装的三种情况
if [[ -d "$TARGET/.git" ]]; then
  echo "✓ skill-orchestrator 已安装: $TARGET"
  echo "  更新: git -C \"$TARGET\" pull"
  exit 0
fi
if [[ -e "$TARGET" ]]; then
  echo "✗ $TARGET 已存在但不是本技能仓库, 为避免覆盖请先处理" >&2
  exit 1
fi

mkdir -p "$ROOT"
echo "→ 从 $REPO_URL 克隆到 $TARGET"
git clone --depth 1 "$REPO_URL" "$TARGET"

# 校验安装产物完整
missing=""
for f in SKILL.md scripts/orchestrator.py; do
  [[ -f "$TARGET/$f" ]] || missing="$missing $f"
done
if [[ -n "$missing" ]]; then
  echo "✗ 安装不完整, 缺少:$missing; 请删除 $TARGET 后重试" >&2
  exit 1
fi

cat <<EOF

✓ skill-orchestrator 安装完成
  位置: $TARGET
  下一步: 新开一个会话 (或重启你的 AI 工具) 让技能被加载,
  然后直接提问即可触发, 例如「这个需求该用什么技能?」

  更新: git -C "$TARGET" pull
  卸载: rm -rf "$TARGET"
EOF
