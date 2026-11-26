# AI 短剧/短视频工作室

[![selftest](https://github.com/ADC1920/AI-Short-Drama-Studio/actions/workflows/selftest.yml/badge.svg)](https://github.com/ADC1920/AI-Short-Drama-Studio/actions/workflows/selftest.yml)

把一句话想法、一段梗概、一个完整剧本，或一部长篇小说，做成可以直接出片的 AI 视频。

整套流程按 Agent Skill 组织，骨架是**十段弹性路由**：一个项目一个目录，每段有明确的最小输入、唯一产物与门禁，**可以从任意一段进入**，不必补齐无关前序；上游改动只把下游标为过期，不自动重写。成本、影响面、验收全部有机检落点，不靠人记。默认出片平台是即梦 Seedance。

## 解决什么问题

AI 短剧的难点很少在单个镜头，多在镜头之间和阶段之间。

**镜头之间**的问题是画面不一致：角色每镜换脸、画风逐镜漂移、转场生硬跳帧、参考图过不了人脸审核。这类问题一旦出现，返工成本远高于前期把分镜做扎实。

**阶段之间**的问题是入口不弹与改稿失控：手上有最终剧本却被要求先写概念稿；只想改第 8 场，却不知道哪些镜头要重出、生成的积分白花了多少。

这个技能把这两类问题都变成结构：

- **分镜先行**。镜号、时长、转场代码、声音设计一次规划清楚，再进入生成环节。
- **素材锚定**。人物和场景各有一套参考图，所有镜头必须通过 `@素材名` 关联，避免纯文字描述带来的漂移。
- **关键帧前置**。每镜先在静态图上解决构图，再让视频模型做运动，把昂贵的视频生成次数压到最低。
- **入口弹性**。十段各有最小输入，缺什么只问什么，不强迫补齐整条流水线。
- **结果可机检**。剧本结构、分镜 JSON、引用关系、提示词血缘、接缝质量、成本账、改稿影响面都有对应脚本量化，不靠肉眼猜。

## 十段弹性路由

| # | 阶段 | 做什么 | 产物 | 门禁 |
|---|---|---|---|---|
| 01 | 概念锚定 | 路径判定（爆款 / 长片 / 艺术片），定引擎、反转链、一句话故事 | `01_story/synopsis.md` | 一句话故事可复述且带得出代价；无下游产物 |
| 02 | 角色圣经 | 三维表、声音可辨测试、反派的刀、对立统一的绑定物 | `01_story/characters.md` | 三维表齐；没有两个同型人物 |
| 03 | 世界观（可选） | 规则四问、知识层级表、道具 setup-payoff、禁对白倒设定 | `01_story/worldbuilding.md` | 「不能做」的限制真拦住过主角；代价在多场累积 |
| 04 | 分场大纲 | 场景数估算、逐场四问、六个审计标签 | `01_story/第N集/treatment.md` | 每场价值有转折；无纯解说场 |
| 05 | 剧本融合 | 资产扫描单、密度分流、@引用名清单 | `02_script/第N集/剧本.md` | `check_script.py` 无错误；有钩子与收尾 |
| 06 | 资产与场景板 | 角色锚点法、场景板、人脸审核规避五法 | `03_assets/`、`场景板/` | `check_refs.py` 无断链 |
| 07 | 表演层（可选） | 五支柱、主档案、倾听与反应、眼神细节 | `04_performance/第N集/acting-vNN.md` | 五支柱自检过；表演段落 4 分以上 |
| 08 | 分镜与提示词 | 工程级分镜（技法 A）或宫格直生（技法 B），逐镜先出关键帧 | 分镜 JSON + 定稿图 + `06_prompts/` | `validate_storyboard.py` PASS；`lint_prompt.py` 无空词 |
| 09 | 出片与台账 | 按素材形态选档逐镜出片，登记同源 | `05_shots/第N集/视频段/*.mp4` | `manifest.py verify` 同源；重生率 ≤10% |
| 10 | 后期与发布 | 拼接、配音、接缝量化、验收、封面文案 | `05_shots/第N集/成片/*.mp4` | `qa_batch.py` 通过；视觉验收真看过 |

**03 与 07 是可选段**。现实题材可跳过 03；表演层未写时，表演要求直接并入 08 段的提示词。可选段未写时 `studio.py status` 显示「可跳过」，不计入未完成。

### 四种入口

| 模式 | 用户怎么说 | 行为 |
|---|---|---|
| 全流程 | 「从零开始：我要做一部 60 秒竖屏悬疑短片」 | 01 → 10 依次推进，**每段完成停下等确认** |
| 单阶段 | 「只做分镜」「只写这三条的提示词」 | 直接进该段，不补无关前序，不生成其他段产物 |
| 接力 | 「以我上传的最终剧本和角色卡为准」 | 登记权威输入，从资料能支持的那段进入 |
| 修订 | 「回到剧本段修第 8 场，先别重做下游」 | 旧版移 `00_project/history/` → 切回 → 只标下游过期 |

判定顺序：先看是否点名阶段（单阶段 / 修订优先）→ 再看是否指定权威输入（接力）→ 都不是才走全流程。

**核心边界**：一次只执行一个阶段；未经用户明确要求与确认，不改其他阶段已定内容；缺资料只问最小项，不补造整套上游。

### 常用命令

```bash
# 建项目：七目录 + 三份控制文件 + 各集集级子目录
python scripts/studio.py init "SD-001_剧名" --episodes 3 --title "剧名"

# 长篇改编：建项目并顺带切分原著章节索引
python scripts/studio.py init "长篇改编" --episodes 24 --novel 原著.txt

python scripts/studio.py status "SD-001_剧名"                  # 十段进度 + 当前焦点段 + 改稿提示 + 成本视图
python scripts/studio.py check  "SD-001_剧名"                  # 串起六类机检
python scripts/studio.py board  "SD-001_剧名"                  # 出单文件 HTML 看板
python scripts/studio.py status "SD-001_剧名" --impact "@顾寒"  # 改了某素材，哪些镜头和成片要重做
python scripts/short_plan.py --script 02_script/脚本.md        # 口播时长预算（短视频形态）
```

段定义、四种入口、阶段间最小输入、回退与下游过期标记见 [`references/stage-router.md`](references/stage-router.md)；数据契约、改稿回流表、单集推进命令见 [`references/studio-workflow.md`](references/studio-workflow.md)。

### 旧项目不必迁移

`studio.py` 会读 `studio.json` 的 `schema` / `layout` 字段与磁盘特征判断布局。v2 项目（根下 `第X集/{剧本.md,分镜/,成片/}` + `素材/`）继续按旧布局跑，上游四段与表演层显示「可跳过」，五个旧工位照常工作。`examples/demo-multi-ep/` 就是这样一个 v2 布局项目，用作兼容回归夹具。

## 两种形态

|  | 短剧形态（默认） | 短视频形态 |
|---|---|---|
| 建项目 | `studio.py init <目录>` | `studio.py init <目录> --form short --target 60` |
| 推进单位 | 每集一个 | 整个项目一条 |
| 脚本 | `02_script/第N集/剧本.md` | `02_script/脚本.md` |
| 末段 | 后期与发布 | 发布台（成片 + 发布包） |
| 特有工艺 | 多集连续性、集间衔接、场景 state 同源 | 口播时长预算、三档节奏、Hook 六分类、发布包四件 |

短视频的口播时长按中文 4.0-4.6 字/秒折算，60 秒只能装 240-276 字；三档节奏（hook 型 0.8-2s/镜、教程型 2-5s/镜、纪录型 3-8s/镜）决定镜头数；单镜不得短于 1.5 秒。发布台要求成片与发布包（封面文案、多平台发布文案、话题标签、评论区引导）双齐。详见 [`references/short-video-studio.md`](references/short-video-studio.md)。

判形态的口径：**一次交付一条、总时长 ≤60 秒、以抓停和发布为导向** → 短视频；**多集、有角色延续、有集间衔接** → 短剧。两者目录兼容，短片起手后续扩成系列不用搬家。

## 门禁、成本与影响面

提示词工艺解决「怎么拍」，这一层解决「做了什么、花了多少、改了之后要重做什么」。判断全部落成脚本：

- **门禁串联**：`studio.py check` 一次跑六类机检——剧本结构（`check_script`）、分镜 JSON（`validate_storyboard`）、@引用断链（`check_refs`）、生成清单同源（`manifest verify`，含提示词 SHA-256 血缘：版号没升但正文改了，报「同名不同内容」）、场景板（`check_scene_plates`）、成品提示词稿（`lint_prompt --line general`）。词层另有单独调用查空词、运镜三参数缺失与否定约束过量。
- **成本三步账**：批量生成前 `estimate_cost.py` 按「镜数 × 实测单价 + 重试余量」估算；生成中 `task_ledger.py` 记 submit / result / cancel 事件（`_tasks.jsonl` 事件溯源），`recover` 只查未回执任务、不重生成；事后 `report` 汇总已花与失败浪费，`studio.py status` 的成本视图在浪费超 10% 时告警。
- **改稿影响面**：`impact_graph.py` 从分镜的 @引用与 S-* 引用建「素材→镜→段」索引，`query` 直接给出要重出哪些段、哪些集的成片要重剪；索引是派生文件，随时可重建。
- **成片量化验收**：`check_seams.py` 对相邻分镜算 SSIM、亮度、色相、饱和、运动持续性五维分；`qa_batch.py` 一键出验收底账；审片标准见 [`references/review-rubric.md`](references/review-rubric.md)（五范围 27 条、四档结论），`review_check.py` 机检审查记录本身是否空壳。
- **对标与原著**：`measure_ref.py` 用 ffmpeg 场景检测，把参考视频与自家成片放同一把尺下测时长、切点、镜长；长篇改编入口是 `novel_index.py`（章节切分、情节点带原文位置可回查、分集区间建议），职责边界见 [`references/novel-adaptation.md`](references/novel-adaptation.md)。

## 给 agent 调用

这套脚本从一开始就是给 agent 用的，不是给人点按钮的。调用面有三条硬约定，全部写成契约：[`references/cli-contract.md`](references/cli-contract.md)。

**一、退出码含义固定**，agent 按码分支而不是只判 `== 0`：

| 码 | 含义 | agent 该做什么 |
|---|---|---|
| 0 | 通过 | 继续 |
| 1 | 检查不通过 | 读 findings 改产物 |
| 2 | 用法/路径错，**没检查成** | 别改产物，先查参数 |
| 3 | 前置条件不满足 | 别原样重试（`task_ledger` 那处重试会重复计费） |
| 4 | 环境或输入损坏 | 需人工介入 |

**二、所有门禁都有 `--json`**，输出统一结构，agent 直接读字段不必解析中文散文：

```json
{
  "ok": false,
  "findings": [
    {"level": "FAIL", "rule": "C11", "file": "sb.json", "line": 0,
     "msg": "分镜漏场：剧本有 3 场，以下场景没有任何镜头覆盖：S3",
     "fix": "为缺的场景补镜头，或确认该场是有意删减并同步改剧本"}
  ],
  "summary": {"total": 1, "fail": 1, "warn": 0}
}
```

`studio.py check --json` 会把各子脚本的 findings 汇总上来，一次拿到全部问题。

**三、分镜必须写 `scene_id`**。剧本有 10 场而分镜只做了 6 场，过去所有机检照样全绿——现在 C11 会判 FAIL 并列出漏了哪几场。老分镜用 [`scripts/migrate_storyboard.py`](scripts/migrate_storyboard.py) 补（默认干跑、`--apply` 自动备份）。

技能自身也有体检：`check_skill.py` 查 front-matter 是否合规、references 有无孤儿与死链、脚本是否都进了索引、长文有无目录；`run_trigger_eval.py` 查 description 与触发话术表是否自洽。两者都在 CI 里跑。

## 安装

克隆到 Agent 的技能目录，目录名保持 `ai-short-drama-studio`（技能 `name` 字段必须与目录同名）：

```bash
# Linux / macOS / Git Bash
git clone https://github.com/ADC1920/AI-Short-Drama-Studio.git ~/.agents/skills/ai-short-drama-studio

# Windows PowerShell
git clone https://github.com/ADC1920/AI-Short-Drama-Studio.git "$env:USERPROFILE\.agents\skills\ai-short-drama-studio"
```

也可以先克隆到任意位置，再把整个目录复制进技能扫描路径（`~/.agents/skills/`、`~/.claude/skills/`，或其他平台的对应目录）。技能本体没有运行时依赖，装好即可使用；脚本按需另装。

## 第一次使用

按手头材料选入口，把对应的话术发给 AI 助手。完整触发示例写在 `SKILL.md` 的「触发示例」一节，共 72 类场景。

1. **从零开始**：说「从零开始：我要做一部 XX」，走 01 → 10，每段完成停下等确认。
2. **只有一句想法**：从 01 起，读 [`references/concept-anchor.md`](references/concept-anchor.md) 选路径（短剧与短视频默认走 C 爆款路径）。
3. **有完整剧本**：说「帮我把这个剧本做成漫剧分镜」，先进 06 备资产，再到 08 读 [`references/agent-prompt.md`](references/agent-prompt.md)（技法 A），把系统提示词贴进新对话再输入剧本。
4. **只有梗概**：到 08 按 [`references/grid-storyboard.md`](references/grid-storyboard.md)（技法 B）生成宫格分镜 JSON，用 `validate_storyboard.py` 机检，再用 `make_grid.py` 拼图。
5. **只做某一段**：直接说「只做分镜」「只写这三条的提示词」，技能不会强迫补齐前序。
6. **参考图被拦**：读 [`references/face-workarounds.md`](references/face-workarounds.md)（06 段技法），从五种规避法里选一种重做素材。

写提示词之前建议先过一遍 `SKILL.md` 的「铁律与核心公式」。生成或拼接出问题时，先查「排障速查」表。

## 目录结构

```
.
├── SKILL.md                 主入口：十段路由、铁律、平台约束、排障、索引（触发示例 72 类）
├── references/              28 篇工艺文档，按场景加载
├── scripts/                 32 个工程脚本，全部带 selftest
├── examples/demo-multi-ep/  最小多集样例（v2 布局，同时用于兼容回归）
├── docs/                    开发导航与历史更新说明
└── .github/workflows/       CI：脚本自检与样例端到端回归
```

`SKILL.md` 末尾有完整的文件与脚本索引，说明每个文件该在什么时候读。`references/` 不必通读，按任务需要取用即可。

安装后的技能会在用户项目里生成这样一套目录：

```
<项目>/
├── studio.json              配置：form / title / aspect / model / episodes / layout
├── 00_project/              brief.md · project-status.md · routing.md · history/
├── 00_inbox/                用户上传资料登记
├── 01_story/                synopsis.md · characters.md · worldbuilding.md · 第N集/treatment.md
├── 02_script/第N集/剧本.md
├── 03_assets/               角色与场景参考图（文件名 = @引用名，根级全剧共用）
├── 04_performance/第N集/    acting-vNN.md
├── 05_shots/第N集/          sb.json · 定稿帧 · _manifest.json · 视频段/ · 成片/ · 尾帧.md
├── 06_prompts/第N集/        cinedance-vNN.md
└── 场景板/                  场景单数据（跨集共用）
```

三份控制文件里不写故事内容——它们是控制面（`brief.md` 项目常量、`project-status.md` 状态与过期标记、`routing.md` 本轮路由），创作产物在 01-06 各目录。

## 脚本

| 脚本 | 用途 | 额外依赖 |
|---|---|---|
| `validate_storyboard.py` | 分镜 JSON 机检：数量、词数、字符上限、排除词、编号重复 | 无 |
| `check_refs.py` | @引用与素材文件核对：断链、待补、闲置素材（v3 找 `03_assets/`，v2 回退 `素材/`） | 无 |
| `check_script.py` | 剧本机检：集号一致、模板占位、@清单、钩子与收尾、场次编号、台词时长预算 | 无 |
| `make_grid.py` | 本地拼宫格，支持 4/6/9/25 | Pillow |
| `init_project.py` | 多集项目脚手架：七目录骨架 + 集级子目录，幂等扩容 | 无 |
| `archive_old_docx.py` | 交付文档旧版归档 | 无 |
| `sync_entity.py` | 技能实体同步：备份、差异扫描、md5 复核 | 无 |
| `check_double_root.py` | 双根部署核对与补链 | 无 |
| `check_seams.py` | 接缝质量量化：SSIM、亮度、色相、饱和、运动持续性 | numpy、Pillow，抽帧需 ffmpeg |
| `qa_batch.py` | 一键验收：接缝检测加清单同源核对，输出底账 | numpy、Pillow，可选 ffmpeg |
| `manifest.py` | 分镜生成清单：提示词版本、参考图、场景 state、定稿状态；verify 含提示词 SHA-256 血缘比对 | 无 |
| `studio.py` | 工作室总控：建项目（七目录 + 三份控制文件，双形态，可带原著索引）、十段进度、门禁串联、改稿影响查询、成本视图、HTML 看板；新旧布局自动判别 | 无 |
| `short_plan.py` | 短视频脚本机检：口播字数区间、单镜下限、时间轴断档、钩子、发布包；`--target` 预算反推 | 无 |
| `check_scene_plates.py` | 场景板机检：字段、ID/state、政策冲突、光线、字数、敏感词、跨文件引用 | 无 |
| `lint_prompt.py` | 提示词词层机检：空词、运镜歧义、运镜三参数缺失、一镜多运镜、步态物理锁、完成态、负面词过量 | 无 |
| `gen_scene_sheet.py` | 场景单生成：数据单源渲染 md，可选调 article-format 出 docx | python-docx（出 docx 时） |
| `trim_clips.py` | 分镜统一裁切到整拍时长，帧精确 | ffmpeg |
| `concat_clips.py` | 分镜段拼接成片：参数一致性核对、流复制拼接、切点列表导出 | ffmpeg |
| `gen_script.py` | 脚本或文档的版本生成引擎，带命中数校验与回放 | 无 |
| `fix_table_pagination.py` | docx 分页修复：表格不跨页、表头重复、防孤行 | python-docx |
| `style_code_blocks.py` | docx 代码块后处理：底纹、左边框、防跨页拆断 | python-docx |
| `tts_voice.py` | 配音合成：按【角色｜profile_id】标注稿调本地 VoiceStudio 逐段出 mp3，读 studio.json 音色表 | 本地 VoiceStudio 服务（可选） |
| `task_ledger.py` | 生成任务台账与成本记账：submit/result/cancel 事件、recover 只查不重生成、report 汇总已花与浪费 | 无 |
| `impact_graph.py` | 改稿影响面依赖图：建「素材→镜→段」索引，query 直接给重出清单并推出成片需重剪 | 无 |
| `estimate_cost.py` | 成本前置估算：镜数 × 实测单价 + 重试余量，未知档位报错不猜 | 无 |
| `measure_ref.py` | 对标测量器：probe 测时长/切点/镜长，diff 与自家成片同一把尺对照 | ffmpeg、ffprobe、numpy、Pillow |
| `review_check.py` | 审查记录格式机检：结论四档自洽、每条有证据、PROVISIONAL 须写明缺什么 | 无 |
| `novel_index.py` | 原著结构索引：章节切分、情节点带 quote+offset 可回查、分集区间建议 | 无 |

依赖一次装齐：

```bash
pip install pillow numpy python-docx
```

ffmpeg 仅 `check_seams.py`、`qa_batch.py`、`trim_clips.py`、`concat_clips.py`、`measure_ref.py` 的实拍部分需要，缺失时相关检查会自动跳过。

## 示例项目

`examples/demo-multi-ep/` 是一套能直接跑通的最小多集项目，包含占位素材、剧本和分镜 JSON。它同时也是 v2 布局的兼容夹具：

```bash
python scripts/validate_storyboard.py "examples/demo-multi-ep/第1集/分镜/sb.json"
python scripts/check_refs.py examples/demo-multi-ep
python scripts/check_script.py examples/demo-multi-ep
python scripts/studio.py status examples/demo-multi-ep     # 应显示「布局 旧多集布局」且上游四段可跳过
python scripts/studio.py check  examples/demo-multi-ep     # 应全部 PASS
```

## 自检

每个脚本都带 `--selftest`，改动后逐个跑一遍（与 CI 同一清单）：

```bash
for s in validate_storyboard check_refs check_script init_project make_grid \
         archive_old_docx sync_entity check_double_root check_seams \
         fix_table_pagination qa_batch manifest trim_clips concat_clips \
         gen_script check_scene_plates gen_scene_sheet style_code_blocks \
         lint_prompt studio short_plan tts_voice estimate_cost task_ledger \
         impact_graph measure_ref review_check novel_index; do
  python "scripts/$s.py" --selftest || echo "FAIL $s"
done
```

CI 在推送到 main 和 PR 时执行同一组自检，并对样例项目跑端到端回归。

## 环境要求

Python 3.9 及以上，Windows、macOS、Linux 均可。技能本体是纯 Markdown，任何支持 Agent Skill 机制的工具都能加载，包括 Claude Code、ZCode、Codex 等。生成环节需要即梦（Seedance）平台账号，具体积分消耗与平台限制见 [`references/jimeng-seedance-2.5.md`](references/jimeng-seedance-2.5.md)。

## 许可证

MIT，详见 [LICENSE](LICENSE)。
