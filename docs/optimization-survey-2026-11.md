# 优化升级调研 · 2026-11

> 调研时点 2026-11-12，基线 v2.7.0。目的：从产品与工程双视角判断本项目还有哪些值得做、哪些不值得做。
> 方法：本仓代码实证（grep 到行）+ GitHub 同类项目对照（`gh api` 核实星数与许可证）+ 中文社区痛点检索（媒体/评测/论坛三源交叉）。
> 本文为调研结论，不含实施；实施另行走版本流程。

## 一、结论速览

本项目的差异化资产是**成片级量化能力**：22 个脚本全带 selftest、`check_seams` 用 ffprobe/SSIM 算接缝、`qa_batch` 出底账、`manifest` 做同源核对。这条线别家没有——同类技能包最多校 JSON 或「用眼睛看」。

所以方向不是补功能广度，而是**把已经量化到成片的这套方法论，往上游还没量化的两个环节延伸：生成任务状态与成本，改稿影响面**。这两处恰好也是社区抱怨最集中的地方。

| 优先级 | 能力 | 缺口性质 | 外部参照 | 预估工作量 |
|---|---|---|---|---|
| P0-1 | 生成任务台账与成本记账 | 全仓零覆盖 | huobao 任务状态机 / waoowaoo UsageCost | 中 |
| P0-2 | 改稿影响面从 mtime 升级为依赖图 | 已有数据未用满 | Toonflow 制作台账 / Jellyfish 实体表 | 中 |
| P0-3 | 内容质量评估与独立审查工位 | 机检只覆盖结构 | zenstory evaluations + RA-01~15 | 大 |
| P1-4 | 提示词与产物血缘哈希绑定 | 只记版号不验内容 | Toonflow SHA-256 revision | 小 |
| P1-5 | 对标拆解的测量器 | 只有定性五维 | zenstory breakdown 七子命令 | 中 |
| P1-6 | 成本前置估算落脚本 | 有纪律无工具 | Toonflow 生成前展示费用 | 小 |
| P2-7 | 上游小说长文分析 | 外推给 onlyshot-drama | zenstory novel_index | 大 |
| P2-8 | 技能拆分与路由 | 单体 335 行 | zenstory 12 skill / shuohao 7 skill | 大（有反作用） |

## 二、现状基线与代码证据

### 2.1 无生成任务状态机

全仓 grep `retry|resume|checkpoint|断点|续跑|幂等`，唯一命中是 `init_project.py` 的目录幂等（`scripts/init_project.py:12`），与生成任务无关。

实际后果：一个镜头生成失败或中断，没有可查的状态记录，也没有「只查不重生成」的恢复路径。用户重跑时无法区分「这段还没跑」和「这段跑过了要重抽」。

### 2.2 无成本记账

全仓 grep `cost|积分|credit|quota|budget|记账`，只在 `short_plan.py` 命中「时长预算」（`scripts/short_plan.py:53` `def budget(target)`），是口播字数预算，与费用无关。

`studio.json` 的 `CONFIG_DEFAULTS`（`scripts/studio.py:42`）字段为 title/aspect/model/episodes/voices/target_seconds，无成本位。

SKILL.md 有「估算 → 确认 → 记账」三步纪律，但「记账」这一环没有脚本落点——全靠对话里写一行。项目跨会话后对不上账。

### 2.3 改稿影响面只做 mtime 粗判

`studio.py status` 的 `impact_warnings` 只比对文件时间，给两类提示：资产晚于成片、分镜晚于视频段（`scripts/studio.py` 约 300 行处 `warnings = impact_warnings(root, us)`）。

而项目手里已有足够的依赖数据没用：

- `diagnostics.py`/`check_refs.py` 能抽出每个镜头的 @引用名
- `check_scene_plates.py` 已做 S-* 跨文件引用核对
- `manifest.json` 每段记了 `script_version` 与 `scene_state`

用这三份数据可以算出精确的「改了角色 A → 哪些镜头用了 @A → 哪些视频段要重出」，现在是靠 mtime 猜。这是本项目自称的核心价值，实现却最薄。

### 2.4 manifest 只比版本标签，不验内容

`manifest.py` 每段记 `script_version`（如 `"v21"`）与 `scene_state`，`verify` 比对相邻段的这两个字符串是否一致。

问题：`script_version` 是人手填的标签，不绑定提示词正文。改了提示词却忘了升版号，`verify` 会给出「同源」的假绿。缺一个提示词内容哈希。

### 2.5 机检只覆盖结构，不覆盖质量

现有 22 个脚本的检查项都是结构性的：字段齐不齐、字数超没超、引用断没断、接缝指标过没过。没有一项回答「这版剧本比上版好吗」。

仓库无 `evaluations/` 目录，无盲评、无 holdout、无真实长篇回归夹具。

## 三、外部对标的四类参照

### 3.1 全流程平台（方法论参照，不照搬形态）

| 项目 | 星 | 关键机制 |
|---|---|---|
| [Toonflow-app](https://github.com/HBAI-Ltd/Toonflow-app) | 21.5k | 资产库 `path` 寻址 + 读取返 SHA-256 `revision`，`update` 拒绝覆盖已变更文件；制作台账四表（成果/生成尝试/片段采用/交付）；生成前必须展示模型/数量/规格/费用并等批准 |
| [huobao-drama](https://github.com/chatfire-AI/huobao-drama) | 17.3k | SQLite 16 表即显式契约；`sys_task` 状态机 `submitting→polling→transferring→downloading→saving→completed`；`/tasks/:id/recover` 只查不重生成；同分镜有运行中任务直接拒绝，重生成须 `force_new` 并提示可能再次计费 |
| [waoowaoo](https://github.com/waooAI/waoowaoo) | 14.8k | `output-registry` 每领域映射唯一 zod strict schema；Temporal 持久执行，`TaskExecutionCheckpoint(stepKey+inputFingerprint)` + `dedupeKey`；`UsageCost`(Decimal 18,6) + `BalanceFreeze`(idempotencyKey) + `ApprovalGrant` 逐次批准 |
| [Jellyfish](https://github.com/Forget-C/Jellyfish) | 7.2k | pydantic `extra="forbid"`；`EvidenceSpan(chunk_id,start_char,end_char,quote)` 让每项提取可回查原文；`shot_preparation_state` 逐项给未就绪原因 |

三条可直接移植到技能包的机制：

1. **资产 revision + 拒绝覆盖**（Toonflow）：不引入数据库也能做——文件内容哈希即 revision，写前比对，变了就报冲突而不是静默覆盖。
2. **只查不重生成的恢复语义**（huobao）：这是成本纪律的工程化。现在纪律只有文字，没有「重跑一遍不会重复计费」的保证。
3. **输出契约锁进工具参数**（huobao）：`save_storyboards` 自带「首批 replace、后续 append、按 shot_number upsert」语义，分批写入天然幂等。我们的脚本目前没有这个语义。

### 3.2 同赛道技能包（能力对照）

| 项目 | 星 | 技能数 | 机检 | 对本项目的意义 |
|---|---|---|---|---|
| [shuohao-skills](https://github.com/eternityspring/shuohao-skills) | 6.5k | 7 | Node stdlib，每 skill 必带 selftest，249/154/329 断言 | 质量门全代码化且每道带击穿用例 |
| [zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills) | 4.1k | 12 | Python 20 个 + 30 unittest，CI 矩阵 3.9/3.10/3.14 + Windows 专 job | 唯一做了评估体系与对标测量器 |
| [seedance2-skill](https://github.com/dexhunter/seedance2-skill) | 4.5k | 1 | 无 | 纯提示词指南，不做对比 |
| [Seedance2-Storyboard-Generator](https://github.com/liangdabiao/Seedance2-Storyboard-Generator) | 2.8k | 1 | 无 | 集间「延长」衔接链路 |

**zenstory 的评估机制值得看细**：`evaluations/` 三层——① 内容质量门禁 16 题材 × 3 replicate、不做 best-of-N、Codex/Kimi 交换 A/B 位置盲评，共 96 份作品 + 192 份报告，fail-closed 要求 bundle sha256 一致；② 真实长篇回归夹具（147KB/20 章/52,552 字原著实跑，21 个产物全 accepted，并复核「派生层能否从源头重建」）；③ 发布前主工作流实跑，记录哪一步需人工介入。它明说不拿回归运行冒充剧本质量证明。

**它的 `short-drama-breakdown`** 把对标做成七子命令测量器：measure（ffprobe 测时长/切点/镜长/代表帧拼图）、transcript、plan、profile、audio、shots、subtitles、subtitle-sheet，差距表六列，且**测法与自家成片同一把尺**。

**它的 `short-drama-review`** 是独立审查工位：`REV-01`~`REV-15` 规则表 + 10 份分范围审查表，结论四档，纪律是「只定位问题不改源文件」「未亲看的媒体一律标未知」。

### 3.3 本项目相对同赛道的真实位置

优势三条，都是工程深度：

1. 22 个脚本全部带 `--selftest` 且 CI 串跑 + `examples/demo-multi-ep` 端到端回归；shuohao 无 CI，zenstory 只有 7 个 selftest，其余项目基本没有。
2. `check_seams` / `qa_batch` / `manifest` / `trim`+`concat_clips` 用 ffprobe/ffmpeg 出数——别家最多校 JSON。
3. `studio.py status` 扫盘判进度 + 改稿回流表 + 双形态，工位化项目治理独有。

缺口五条：无任务状态与成本、无内容质量评估、无上游小说分析、对标无测量器、无独立审查工位。

### 3.4 中文社区真实痛点（2026 年）

| 痛点 | 具体表现 | 来源 |
|---|---|---|
| 角色跨镜变脸 | 正脸锁住，侧脸/远景/换光就变人；多角色同框撞脸 | chinanews.com.cn、news.qq.com |
| 动起来才崩 | 图生视频后大幅动作时脸部细节下降，穿模、手指穿透、肢体反折 | juejin.cn |
| 抽卡不可控 | 首次可用率 50–70%，行内按 10:1 估；95 张分镜从约 1700 张筛出 | sincosphere.cn、elserstudio.ai |
| 改一处推倒重来 | 角色微调就要重跑整条，团队「用流程试错、一次次推翻重来」 | lmtw.com、huxiu.com |
| 工具碎、版本乱 | 「在脚本、图片、视频模型与剪辑工具之间反复切换，同一角色每换一次工具就可能换脸，素材版本难以对齐，返工成为常态」 | jiemian.com、sspai.com |

成本结构：视频生成占模型费 92–97%，废片不进正片但算力照付；90 秒一集一次过 ¥45–200，含重生成 ¥180–510；个人账本算力+废片约 1 元/秒。

**关键判断**：把「角色/场景资产库 + 局部重拍」做成核心，一刀能解掉变脸、改稿返工、版本混乱三件事——因为真实亏损不在单价，在重生成废片。这与 P0-1、P0-2 完全同向。

## 四、建议清单

### P0-1 生成任务台账与成本记账

**缺口**：无任务状态、无费用记录（2.1/2.2 证据）。

**做法**（不引入数据库，保持纯文件）：

新增 `scripts/task_ledger.py`，在项目 `_tasks.jsonl` 里按行追加事件：

- `submit`：镜号、提示词哈希、模型、预估积分、时间戳
- `result`：同镜号、状态（success/failed/cancelled）、实耗积分、产物路径
- `recover`：只读取汇总，列出「已提交未回执」的镜号，**不触发任何生成**

同时给 `studio.py status` 加一节成本视图：本集已花、预估剩余、失败重抽耗掉多少。SKILL.md 的「估算 → 确认 → 记账」第三步从此有落点。

**验收**：① 三态（success/failed/cancelled）都能落账；② 重复 submit 同镜号时提示「已有运行中任务」并拒绝，除非显式 `--force`；③ `recover` 在无网络环境下只读不写；④ selftest 覆盖「失败重抽不重复计费统计」这条不变量。

**参照**：huobao 的 `/tasks/:id/recover` 只查不重生成 + 同分镜运行中拒绝；waoowaoo 的 `UsageCost` + `dedupeKey`。

### P0-2 改稿影响面从 mtime 升级为依赖图

**缺口**：已宣称的核心价值，实现只有文件时间比对（2.3 证据）。

**做法**：复用现有三份数据，不新建契约。

- 从 `分镜/*.json` 抽每镜的 `@引用名` 与 `S-*` 引用
- 从 `_manifest.json` 抽每段对应的镜号
- 建「素材/场景 → 镜号 → 视频段」三向索引，输出到 `_impact.json`
- `studio.py status --impact <改动>` 直接回答「改了 @顾寒，要重出哪些段」

**验收**：① 给定一个素材名，能列出精确镜号与视频段，不是「有提示」而是「有清单」；② 素材改名后索引报断链（与 check_refs 同源）；③ 与 mtime 提示并存时以依赖图为准，mtime 降为兜底。

**参照**：Jellyfish 的实体表 + `shot_preparation_state` 逐项给未就绪原因；Toonflow 制作台账四表。

### P0-3 内容质量评估与独立审查工位

**缺口**：机检只覆盖结构（2.5 证据）。

**做法**分两步，先做能落地的：

- **第一步（小）**：新增 `references/review-rubric.md`，把审查做成可勾选的规则表而非散文。分范围（剧本 / 资产 / 分镜 / 提示词 / 成片），每条给「不通过的具体样子」。结论四档：通过 / 有保留通过 / 退回修改 / 证据不足。纪律继承现有「未亲看不得声称通过」。
- **第二步（大）**：`scripts/quality_gate.py` 吃一份 `cases/` 夹具目录，同题材多版本两两盲评、记录偏好、出统计。不做 best-of-N，固定重复次数。

**验收**：① 第一步的规则表每条能对应到已有脚本或明确的人工判定项，不留空话；② 第二步给出「同一夹具跑两次结论是否稳定」的自检；③ 明说不拿回归运行冒充质量证明（学 zenstory 的诚实声明）。

**参照**：zenstory 的 evaluations 三层 + REV-01~15。

### P1-4 提示词与产物血缘哈希绑定

**缺口**：`script_version` 是手填标签，忘升版就假绿（2.4 证据）。

**做法**：`manifest.py` 在写入时对提示词正文算 sha256 前 12 位一并记入；`verify` 除了比版号，还比哈希——版号相同但哈希不同，直接报「同名不同内容」。

**验收**：① 改提示词不改版号时 `verify` 必须报错；② 老 manifest 无哈希字段时降级为警告不阻断（向后兼容）；③ selftest 加「同名不同内容」用例。

**参照**：Toonflow 的 SHA-256 revision + 拒绝覆盖已变更。

### P1-5 对标拆解的测量器

**缺口**：只有五维定性，无量化（SKILL.md 对标参考流程节）。

**做法**：新增 `scripts/measure_ref.py`，对参考视频与自家成片跑同一套 ffprobe 指标：总时长、平均镜长、切点分布、对白密度、黑场段，出两栏对照表。复用现有 `check_seams` 的探针代码，不重写。

**验收**：① 同一把尺同时测参考片与自家片；② 拿不到原片时明确报「无法测量」而不是估数；③ 输出直接喂给 SKILL.md 的「保留/更换两栏清单」。

**参照**：zenstory breakdown 的 measure 子命令。

### P1-6 成本前置估算落脚本

**缺口**：有纪律无工具（2.2 证据）。

**做法**：`scripts/estimate_cost.py` 读分镜 JSON 的镜数与时长，按 `references/jimeng-seedance-2.5.md` 的积分数出总量，加可配重试余量，输出「镜数 × 单条积分 = 总量」。一行命令替代人工算。

**验收**：① 镜数来自分镜 JSON 而非手数；② 重试余量可配，默认与 SKILL.md 的 ~10% 重生预算一致；③ 输出可直接贴进确认话术。

### P2-7 上游小说长文分析

**缺口**：SKILL.md 明确把策划层外推给 `onlyshot-drama`（SKILL.md 第 17 行「策划层指针」）。

**判断**：这是**有意为之的边界，不是缺口**。做它等于和 onlyshot-drama 职责重叠，且需要章节索引/改编价值/分集候选这一整套，成本远大于收益。**建议不做**，除非将来 onlyshot-drama 不再维护。

### P2-8 技能拆分与路由

**缺口**：单体 SKILL.md 335 行，无法「只装某阶段」。zenstory 12 skill、shuohao 7 skill 都是独立安装单元。

**判断**：**建议暂不做**。拆分带来三个代价——① 用户要装多份、触发词要重新分配；② 跨 skill 的数据契约要显式化（现在靠同一份 SKILL.md 隐式共享）；③ 现有 22 脚本的 `studio.py check` 串联优势会被打散。只有当「用户在只做分镜、不想载入整个工作室」这条需求被反复提出时才值得做。

## 五、不建议做的

- **Web 前端 / 可视化画布**：v2.0.0 已明确决策「不引入 Web 前端或平台 API 依赖」，理由是避免把可移植技能绑死在某平台页面结构上。这条决策在本次调研中依然成立，Toonflow/waoowaoo 的重资产形态正好反证了轻量技能包的价值。
- **引入数据库**：SQLite 16 表（huobao）不适合技能包形态，`jsonl` + 文件哈希已能覆盖同等语义。
- **自建模型调用层**：本项目定位是「告诉人怎么用」，不是「替人调 API」。`tts_voice.py` 是唯一例外，因为它接的是本地回环、无需鉴权、且「给定 profile_id 批量合成」是可判定对错的事。

## 六、待用户决策

1. P0 三条是否全做，还是先做 P0-1 + P0-2（这两条同向解决「返工成本」，且都不需要评估体系这种重投入）。
2. P0-3 第二步（评估体系）是否值得做——它最贵，且需要真实项目样本才能校准。
3. 如果只选一条，我的判断是 **P0-2**：它复用已有数据、直接兑现项目已宣称的核心价值、且社区痛点证据最强（「改一处推倒重来」是最高频抱怨）。

## 七、来源

- 本仓代码证据：`scripts/studio.py`、`scripts/manifest.py`、`scripts/short_plan.py`、`scripts/init_project.py`（2026-11-12 grep 实测）
- GitHub 元数据：`gh api repos/{owner}/{repo}`（2026-11-12 核实星数与许可证）
- 社区痛点：jiemian.com、sincosphere.cn、sspai.com、chinanews.com.cn、v2ex.com、lmtw.com、juejin.cn、huxiu.com、elserstudio.ai
- 前次调研存档：`docs/ecosystem-survey-2026-10.md`、`docs/ecosystem-survey-2026-10-short-video.md`、`docs/skill-updates-2026-10.md`
