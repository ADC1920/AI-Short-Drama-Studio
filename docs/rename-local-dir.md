# 本地工作区目录改名（在 ZCode 会话关闭后执行）

## 为什么不能现场改

本会话的工作目录被固定在 `Al-short-play-video-creation`，Bash 工具每次执行后都会把 cwd 重置回该路径，目录句柄因此被持有，`mv` 与 `Rename-Item` 都报 `Device or resource busy`。

已验证：同级其他目录可正常改名，唯独此目录不行，确认占用源就是会话 cwd 句柄，不是别的进程。

## 执行方式

关闭本 ZCode 会话后，用 PowerShell 7 执行：

```powershell
pwsh -NoProfile -Command "Rename-Item -LiteralPath 'D:\Computer Software\24-Zcode DeskTop\Zcode Data\Al-short-play-video-creation' -NewName 'AI-Short-Drama-Studio'"
```

或在资源管理器里直接重命名。

## 改名后需要确认的

目录名 `Al-short-play-video-creation` 里是 **`Al`（大写 A 加小写 l）**，不是 `AI`。这个拼写错误存在已久，改名为 `AI-Short-Drama-Studio` 时会一并纠正。

改完后仓库本身无需任何调整——`.git` 随目录移动，remote 已指向新仓库地址 `https://github.com/ADC1920/AI-Short-Drama-Studio.git`。

验证：

```powershell
cd 'D:\Computer Software\24-Zcode DeskTop\Zcode Data\AI-Short-Drama-Studio'
git status --short          # 应为空
git remote -v               # 应指向 AI-Short-Drama-Studio
python scripts/studio.py --selftest
```

## 已经完成的改名（无需再做）

| 位置 | 新名 | 状态 |
|---|---|---|
| 技能 `name` 字段 | `ai-short-drama-studio` | 已完成，v2.2.0 |
| 本机技能实体目录 | `~/.agents/skills/ai-short-drama-studio` | 已完成并同步（40 件 md5 全等） |
| GitHub 仓库 | `AI-Short-Drama-Studio` | 已完成，旧地址 301 重定向 |
| GitHub 本地 remote | 新地址 | 已更新 |
| 触发登记表 | `ai-short-drama-studio` | 已完成 |
| 仓库内引用面（9 文件） | 新名 | 已完成并合入 main |
| 本地工作区目录 | `AI-Short-Drama-Studio` | **待执行（需会话关闭）** |
