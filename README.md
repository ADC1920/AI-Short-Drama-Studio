# AI 短剧创作工作流

[![selftest](https://github.com/ADC1920/AI-short-play-video-creation/actions/workflows/selftest.yml/badge.svg)](https://github.com/ADC1920/AI-short-play-video-creation/actions/workflows/selftest.yml)

把剧本或一句话剧情梗概，做成可以直接出片的 AI 短剧视频。整套流程按 Agent Skill 组织，覆盖分镜、素材、逐镜生成、配音和后期拼接，动态漫、漫剧、写实风都适用，默认出片平台是即梦 Seedance。

安装之后直接对 AI 助手说「帮我把这个剧本做成漫剧分镜」，技能会被触发并接管后续流程。

## 解决什么问题

AI 短剧的难点通常不在单个镜头，而在镜头之间的连贯。角色每镜换脸、风格逐镜漂移、转场生硬跳帧、参考图过不了人脸审核，这些问题一旦出现，返工成本远高于前期把分镜做扎实。

这个技能把行业里反复验证过的做法固化成可执行的步骤：

- 分镜先行。镜号、时长、转场代码、声音设计一次规划清楚，再进入生成环节。
- 素材锚定。人物和场景各有一套参考图，所有镜头必须通过 `@素材名` 关联，避免纯文字描述带来的漂移。
- 关键帧前置。每镜先在静态图上解决构图，再让视频模型做运动，把昂贵的视频生成次数压到最低。
- 结果可机检。分镜 JSON、引用关系、接缝质量都有对应脚本量化，不靠肉眼猜。

## 三条制作路线

| 路线 | 手头有什么 | 怎么做 | 产出 |
|---|---|---|---|
| A 分镜智能体 | 完整剧本 | 加载系统提示词，由模型产出工程级分镜蓝图 | 镜号、时长、转场、声音设计齐全的分镜表 |
| B 宫格分镜直生 | 一句话或一段梗概 | 生成九宫格分镜 JSON，拼成一张宫格图，一张图直出 15 秒 | 9/25 宫格分镜图与直生视频 |
| C 人脸审核规避 | 参考图被人脸检测拦截 | 五种规避法，可叠加在 A、B 之上 | 能过审的人物参考图方案 |

整部短剧或小说改编走多集工作流，先分集，再逐集套用 A 或 B，素材全剧共用一套。

## 安装

克隆到 Agent 的技能目录，目录名保持 `ai-short-play-video-creation`：

```bash
# Linux / macOS / Git Bash
git clone https://github.com/ADC1920/AI-short-play-video-creation.git ~/.agents/skills/ai-short-play-video-creation

# Windows PowerShell
git clone https://github.com/ADC1920/AI-short-play-video-creation.git "$env:USERPROFILE\.agents\skills\ai-short-play-video-creation"
```

也可以先克隆到任意位置，再把整个目录复制进技能扫描路径（`~/.agents/skills/`、`~/.claude/skills/`，或其他平台的对应目录）。技能本身没有运行时依赖，装好即可使用，脚本按需另装。

## 第一次使用

按手头材料选一条路线，把对应的话术发给 AI 助手即可。更完整的触发示例写在 `SKILL.md` 的「触发示例」一节，共 28 类场景。

1. 有完整剧本：让助手读 `references/agent-prompt.md`，把其中的系统提示词贴进新对话，再输入剧本。
2. 只有梗概：让助手按 `references/grid-storyboard.md` 生成宫格分镜 JSON，用 `scripts/validate_storyboard.py` 机检，再用 `scripts/make_grid.py` 拼图。
3. 参考图被拦：让助手读 `references/face-workarounds.md`，从五种规避法里选一种重做素材。

写提示词之前，建议先过一遍 `SKILL.md` 的「铁律与核心公式」。生成或拼接出问题时，先查「排障速查」表。

## 目录结构

```
.
├── SKILL.md                 主入口：路线、铁律、平台约束、排障、索引
├── references/              14 篇工艺文档，按场景加载
├── scripts/                 15 个工程脚本，全部带 selftest
├── examples/demo-multi-ep/  最小多集样例，同时用于回归测试
├── docs/                    工作区导航与技能更新说明
└── .github/workflows/       CI：脚本自检与样例端到端回归
```

`SKILL.md` 末尾有完整的文件与脚本索引，说明每个文件该在什么时候读。`references/` 不必通读，按任务需要取用即可。

## 脚本

| 脚本 | 用途 | 额外依赖 |
|---|---|---|
| `validate_storyboard.py` | 分镜 JSON 机检：数量、词数、字符上限、排除词、编号重复 | 无 |
| `check_refs.py` | @引用与素材文件核对：断链、待补、闲置素材 | 无 |
| `make_grid.py` | 本地拼宫格，支持 4/6/9/25 宫格 | Pillow |
| `init_project.py` | 多集项目脚手架，幂等扩容 | 无 |
| `archive_old_docx.py` | 交付文档旧版归档 | 无 |
| `sync_entity.py` | 技能实体同步：备份、差异扫描、md5 复核 | 无 |
| `check_double_root.py` | 双根部署核对与补链 | 无 |
| `check_seams.py` | 接缝质量量化：SSIM、亮度、色相、饱和、运动持续性 | numpy、Pillow，抽帧需 ffmpeg |
| `qa_batch.py` | 一键验收：接缝检测加清单同源核对，输出底账 | numpy、Pillow，可选 ffmpeg |
| `manifest.py` | 分镜生成清单：提示词版本、参考图、场景 state、定稿状态 | 无 |
| `check_scene_plates.py` | 场景板机检：字段、ID/state、政策冲突、光线、字数、敏感词、跨文件引用 | 无 |
| `gen_scene_sheet.py` | 场景单生成：数据单源渲染 md，可选调 article-format 出 docx | python-docx（出 docx 时） |
| `trim_clips.py` | 分镜统一裁切到整拍时长，帧精确 | ffmpeg |
| `gen_script.py` | 脚本或文档的版本生成引擎，带命中数校验与回放 | 无 |
| `fix_table_pagination.py` | docx 分页修复：表格不跨页、表头重复、防孤行 | python-docx |

依赖一次装齐：

```bash
pip install pillow numpy python-docx
```

ffmpeg 仅 `check_seams.py`、`qa_batch.py`、`trim_clips.py` 的实拍部分需要，缺失时相关检查会自动跳过。

## 示例项目

`examples/demo-multi-ep/` 是一套能直接跑通的最小多集项目，包含占位素材、剧本和分镜 JSON。可以照着它搭自己的目录，也可以用它验证脚本：

```bash
python scripts/validate_storyboard.py "examples/demo-multi-ep/第1集/分镜/sb.json"
python scripts/check_refs.py examples/demo-multi-ep
```

## 自检

每个脚本都带 `--selftest`，改动后逐个跑一遍：

```bash
python scripts/validate_storyboard.py --selftest
python scripts/make_grid.py --selftest
python scripts/check_refs.py --selftest
python scripts/init_project.py --selftest
python scripts/archive_old_docx.py --selftest
python scripts/sync_entity.py --selftest
python scripts/check_double_root.py --selftest
python scripts/check_seams.py --selftest
python scripts/fix_table_pagination.py --selftest
python scripts/qa_batch.py --selftest
python scripts/manifest.py --selftest
python scripts/trim_clips.py --selftest
python scripts/gen_script.py --selftest
python scripts/check_scene_plates.py --selftest
python scripts/gen_scene_sheet.py --selftest
```

CI 在每次 push 和 PR 时执行同一组自检，并对样例项目跑端到端回归。

## 环境要求

Python 3.9 及以上，Windows、macOS、Linux 均可。技能本体是纯 Markdown，任何支持 Agent Skill 机制的工具都能加载，包括 Claude Code、ZCode、Codex 等。生成环节需要对应的图片和视频平台账号，具体积分消耗与平台限制见 `references/jimeng-seedance-2.5.md`。
