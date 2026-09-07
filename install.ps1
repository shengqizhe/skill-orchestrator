#requires -Version 5.1
<#
skill-orchestrator 安装脚本 (Windows PowerShell)

用法: 把技能装进「你正在使用的 AI 工具」的技能库 —— 第一个参数 = 技能库根目录。
  方式一(推荐, 免命令行): 把 README 里的安装指令发给你的 AI 工具,
    它用宿主自身的机制克隆到自己的技能库, 不需要本脚本。
  方式二(终端一条命令, 仓库公开后可用):
    irm https://raw.githubusercontent.com/shengqizhe/skill-orchestrator/main/install.ps1 -OutFile "$env:TEMP\sio-install.ps1"
    powershell -ExecutionPolicy Bypass -File "$env:TEMP\sio-install.ps1" "$env:USERPROFILE\.zcode\skills"
  不传参数时: 若默认的 ZCode 技能库 (%USERPROFILE%\.zcode\skills) 已存在则装到那里;
    否则报错提示显式传参 (不擅自建目录、不做多宿主探测)。
  其他宿主请显式传参: Codex 用 .codex\skills, Claude Code 用 .claude\skills。

环境变量 SKILL_ORCHESTRATOR_REPO_URL 可覆盖仓库地址 (测试/镜像场景)。
#>
param([string]$LibraryRoot)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch { }

$RepoUrl = if ($env:SKILL_ORCHESTRATOR_REPO_URL) { $env:SKILL_ORCHESTRATOR_REPO_URL } else { 'https://github.com/shengqizhe/skill-orchestrator.git' }
$SkillName = 'skill-orchestrator'
$DefaultRoot = Join-Path $env:USERPROFILE '.zcode\skills'

if ([string]::IsNullOrWhiteSpace($LibraryRoot)) {
  if (Test-Path -LiteralPath $DefaultRoot) {
    $LibraryRoot = $DefaultRoot
  } else {
    Write-Host @"
用法: install.ps1 [技能库根目录]

把技能装进「你正在使用的 AI 工具」的技能库:
  ZCode:        $DefaultRoot
  Codex:        `$env:USERPROFILE\.codex\skills
  Claude Code:  `$env:USERPROFILE\.claude\skills

本机未发现默认的 ZCode 技能库 ($DefaultRoot),
请显式传入技能库根目录, 例如:
  powershell -ExecutionPolicy Bypass -File install.ps1 "`$env:USERPROFILE\.codex\skills"
"@ -ForegroundColor Yellow
    exit 2
  }
}

$Root = $LibraryRoot.TrimEnd('\')
$Target = Join-Path $Root $SkillName

# 已有安装的三种情况
if (Test-Path -LiteralPath (Join-Path $Target '.git')) {
  Write-Host "OK skill-orchestrator 已安装: $Target"
  Write-Host "  更新: git -C `"$Target`" pull"
  exit 0
}
if (Test-Path -LiteralPath $Target) {
  Write-Host "X $Target 已存在但不是本技能仓库, 为避免覆盖请先处理" -ForegroundColor Red
  exit 1
}

New-Item -ItemType Directory -Path $Root -Force | Out-Null
Write-Host "→ 从 $RepoUrl 克隆到 $Target"
git clone --depth 1 $RepoUrl $Target
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 校验安装产物完整
$missing = @()
foreach ($f in @('SKILL.md', 'scripts\orchestrator.py')) {
  if (-not (Test-Path -LiteralPath (Join-Path $Target $f))) { $missing += $f }
}
if ($missing.Count -gt 0) {
  Write-Host "X 安装不完整, 缺少: $($missing -join ', '); 请删除 $Target 后重试" -ForegroundColor Red
  exit 1
}

Write-Host @"

OK skill-orchestrator 安装完成
  位置: $Target
  下一步: 新开一个会话 (或重启你的 AI 工具) 让技能被加载,
  然后直接提问即可触发, 例如「这个需求该用什么技能?」

  更新: git -C `"$Target`" pull
  卸载: Remove-Item -Recurse -Force `"$Target`"
"@
