# 重构方案：十段弹性路由（吸收 AI STUDIO 洋子工作流）

> 状态：已确认执行（用户四问选型：十段弹性路由 / 完全照搬七目录 / 四项吸收全选 / 按本项目口径改写）
> 来源：`E:\1-临时文件存放\剧本到视频提示词自动化SKILL工作流V1版本\01-Codex-AI STUDIO洋子-剧本到视频提示词SKILL工程安装包`（35 件，8 个技能 + 模板 + 安装脚本）
> 目标版本：v3.0.0

## 一、为什么改

本项目 v2.x 的骨架是「五工位顺序流水线」：剧本台 → 角色与场景台 → 分镜台 → 出片台 → 后期台。它解决的是「产物在哪、改稿往哪回流」，但入口只有一种——顺序推进。对方工作流解决的是另外三个问题，本项目目前没有对应结构：

1. **入口弹性**。用户手上有最终剧本、有角色卡、只有一句概念，三种情况走同一条流水线，意味着强迫补齐无关前序。对方的四种模式（全流程 / 单阶段 / 接力 / 修订）让任何阶段都能单独进入。
2. **上游创作段缺席**。本项目的剧本台直接吃「一句话梗概或完整剧本」，概念锚定、角色圣经、分场大纲这些中间产物没有落点，也没有门禁。上游由外部技能 `onlyshot-drama` 承担，但那是另一个技能，不共享项目目录与状态。
3. **阶段切换无状态记录**。改稿时「哪些下游可能过期」现在靠 `studio.py status` 比对文件时间，没有显式的路由记录与人工确认节点。

## 二、目标形态

### 2.1 十段阶段表

| # | 阶段 | 最小输入 | 标准输出 | 主要机检 |
|---|---|---|---|---|
| 01 | 概念锚定 | 一句话需求 / brief.md | `01_story/synopsis.md` | 人工（三路径模板齐） |
| 02 | 角色圣经 | 概念或已有故事 | `01_story/characters.md` | 人工（三维表 + 声音可辨测试） |
| 03 | 世界观（可选） | 复杂世界规则需求 | `01_story/worldbuilding.md` | 人工（系统能力/代价/知识层级） |
| 04 | 分场大纲 | 概念+角色+目标时长 | `01_story/第N集/treatment.md` | 人工（逐场四问 + 审计标签） |
| 05 | 剧本融合 | 已有剧本资产或已确认上游 | `02_script/第N集/剧本.md` | `check_script.py` |
| 06 | 资产与场景板 | 最终剧本 | `03_assets/**`、`场景板/` | `check_refs.py`、`check_scene_plates.py` |
| 07 | 表演层 | 场景/镜头 + 角色信息 | `04_performance/第N集/acting-v01.md` | 人工（五支柱自检） |
| 08 | 分镜与提示词 | 镜头目标 + 资产参考 + 表演 | `05_shots/第N集/sb.json`、`06_prompts/第N集/*.md` | `validate_storyboard.py`、`lint_prompt.py` |
| 09 | 出片与台账 | 分镜 JSON + 定稿帧 | `05_shots/第N集/视频段/*.mp4` | `manifest.py verify`、`task_ledger.py` |
| 10 | 后期与发布 | 视频段 | `05_shots/第N集/成片/*.mp4`、发布包 | `qa_batch.py`、`check_seams.py` |

**五工位不消失，降为十段中的五段**：剧本台=05、角色与场景台=06、分镜台=08、出片台=09、后期台=10。01-04 与 07 是新增段。这样旧用户的话术（「剧本台」「分镜台」）仍能命中，只是它们现在属于十段路线的中间站。

### 2.2 四种入口模式

| 模式 | 触发 | 行为 |
|---|---|---|
| 全流程 | 「从零开始 / 做一部……」 | 01 → 10 依次推进，每段完成后停下等确认 |
| 单阶段 | 「只做分镜 / 只做 CINEDANCE」 | 直接进目标段，不补无关前序 |
| 接力 | 用户已有剧本、角色卡、资产图 | 从资料能支持的段进入，登记权威输入 |
| 修订 | 「回到剧本段修第 8 场」 | 留版本 → 切回上游 → 标下游「可能过期」→ 不自动重写 |

### 2.3 目录契约（完全照搬七目录 + 集级子目录）

```
<项目>/
├── studio.json                    配置：form / title / aspect / model / episodes
├── 00_project/
│   ├── brief.md                   一句话需求、受众、平台、时长、类型、视觉方向、预算、禁项
│   ├── project-status.md          运行模式 / 目标阶段 / 权威输入 / 已确认文件 / 可能过期下游
│   ├── routing.md                 当前阶段 / 唯一输出 / 本阶段允许读取 / 方法来源
│   └── history/                   修订留档（旧版移入，不删除）
├── 00_inbox/                      用户上传资料登记
├── 01_story/
│   ├── synopsis.md                01 概念锚定
│   ├── characters.md              02 角色圣经
│   ├── worldbuilding.md           03 世界观（可选，无则缺省）
│   └── 第N集/treatment.md         04 分场大纲
├── 02_script/
│   └── 第N集/剧本.md              05 剧本融合
├── 03_assets/                     06 资产：根级全剧共用，第N集/ 放集专属
├── 04_performance/
│   └── 第N集/acting-v01.md        07 表演层
├── 05_shots/
│   └── 第N集/
│       ├── sb.json                08 分镜 JSON
│       ├── grid01.png             定稿关键帧
│       ├── _manifest.json         09 生成清单
│       ├── 视频段/                09 出片产物
│       └── 成片/                  10 后期产物
├── 06_prompts/
│   └── 第N集/cinedance-v01.md     08 提示词（可执行成品）
└── 场景板/                        场景板数据（与 03_assets 同级，跨集共用）
```

多集处理：七个顶级目录解决「阶段分层」，集级产物在阶段目录下再用 `第N集/` 子目录隔离。全剧共用资产（人物参考图、场景板）留在根级。这与 v2.x 的 `第X集/{剧本.md,分镜/,成片/}` 差别只是多了一层阶段目录，`第X集/` 仍是集级容器。

### 2.4 吸收的四项内容

| 吸收项 | 落点 | 与既有文档的关系 |
|---|---|---|
| 表演五支柱 | 新增 `references/performance-craft.md` | 补分镜台的表演层；与 `facs-micro-expression.md`（微表情四区）、`action-previs.md`（打戏动力链）互补，不重叠 |
| 世界观规则模板 | 新增 `references/worldbuilding-rules.md` | 本项目零覆盖；从对方俄文模板重写为中文，补「知识层级表」「设定展示规则」 |
| 概念三路径分流 | 新增 `references/concept-anchor.md` | 补 01 段；C 路径（爆款引擎）与本项目短剧形态直接对接，A/B 路径作长片与艺术片备用 |
| 分场审计与剧本融合协议 | 新增 `references/treatment-audit.md` | 补 04/05 段；现有 `check_script.py` 只看集号与占位，这份补场景级四问与六个审计标签 |

### 2.5 口径统一（不照搬部分）

对方材料里有三类与本项目既有判定冲突的内容，一律按本项目口径改写：

1. **品牌词**：Higgsfield Soul 2.0 / Soul Cinema / Lira / NBP / Seedream 4.5 / GPT Image 2 → 抽象为「角色图模型 / 场景图模型 / 编辑模型（首选）/ 纹理修复模型 / 精修模型（末选）」。理由：本项目 v1.0 已执行正文品牌词清零，品牌写死会随平台迭代过期。
2. **质量词**：电影级静态剧照、超写实摄影细节、ARRI Alexa LF、Cooke S4 → 只保留可观察部分（景深范围、颗粒形态、焦段视觉后果），删除纯形容词。理由：`lint_prompt.py` 把这些词判为空词，文档不能与机检互相打脸。
3. **强制英文/俄文措辞**：对方「必须纯中文输出」的措辞保留，但把「绝对不能用 rule of thirds」这类禁令改写为「用三分法构图」这类正向说法（与「正向 > 反向」规则一致）。

## 三、影响范围

### 3.1 需要改的脚本（路径契约层）

| 脚本 | 当前假设 | 改法 |
|---|---|---|
| `studio.py` | `units()` 扫 `第X集/` 目录；`collect()` 按三件目录判进度 | 新增 `LAYOUT` 常量映射阶段→目录；`units()` 从 `02_script/第N集` 取集号；`collect()` 十段扫盘 |
| `init_project.py` | 建 `第X集/{剧本.md,分镜/,成片/}` | 建七目录骨架 + 集级子目录 |
| `impact_graph.py` | `第X集/分镜` | 改 `05_shots/第N集` |
| `concat_clips.py` | 从 `分镜/视频段` 推断 `成片/` | 兼容新旧两种推断 |
| `check_script.py` | 扫 `第N集/剧本.md` | 扫 `02_script/第N集/剧本.md`，兼容旧路径 |
| `check_refs.py` | 默认 `<项目>/素材` | 默认 `<项目>/03_assets`，回退 `素材/` |

其余 22 个脚本接受任意路径参数，不需改动。

### 3.2 需要改的文档

- `SKILL.md`：十段图替换五工位图；触发示例补十段话术；铁律区补「一次只执行一个阶段」「未确认不改其他阶段」；更新记录加 v3.0.0
- 新增 5 篇 references（stage-router / concept-anchor / worldbuilding-rules / treatment-audit / performance-craft）
- `references/studio-workflow.md`：五工位定义改为十段映射表，保留改稿回流表
- `README.md`、`AGENTS.md`、`docs/project-info.md`：结构与脚本口径同步
- `.github/workflows/selftest.yml`：脚本数不变（28），但需确认路径改动后仍绿

### 3.3 不改的部分

- 所有工艺文档正文（camera-grammar / visual-lexicon / prompt-craft / frame-industrial / scene-plates / continuity-log / transition-editing / audio-voice / publish-ops / asset-workflow / character-design / emotion-beat-curve / action-previs / facs-micro-expression / review-rubric / novel-adaptation / agent-prompt / grid-storyboard / face-workarounds / short-video-studio / jimeng-seedance-2.5）
- 28 个脚本的核心算法（只改路径解析层）
- 短视频形态（`--form short`）：单条项目不涉及多集，七目录同样适用，脚本.md 落 `02_script/剧本.md`

## 四、迁移路径

1. 建 `studio.py` 的布局解析层，新旧布局并存（新项目用七目录，检测到旧 `第X集/剧本.md` 自动按旧布局解析）
2. 改 `init_project.py` 生成七目录
3. 逐个改 5 个脚本的路径常量
4. 跑 28 脚本 selftest 全绿
5. 用 `examples/demo-multi-ep/` 验证：迁到新结构，`studio.py status/check` 结果与迁移前一致
6. 同步实体

**为什么不直接废弃旧布局**：`examples/demo-multi-ep/` 是 CI 回归夹具，且用户可能已有本地项目。保留兼容层的成本是 `studio.py` 里约 40 行布局判断，远低于迁移所有历史项目的成本。

## 五、验证方式

1. `python scripts/studio.py --selftest` 覆盖：空项目 → 全流程 10 段 → 门禁全绿 → 回流提示
2. 其余 27 脚本 `--selftest` 全绿
3. `examples/demo-multi-ep/` 端到端：`studio.py status` 输出十段进度，`studio.py check` 全绿
4. 手工走查：新建项目 → 只做 08 段（单阶段模式）→ 确认不逼迫补 01-07
5. CI（`.github/workflows/selftest.yml`）跑绿

## 六、回滚方式

- 改动前 HEAD = `e203e43`（main 干净工作树）
- 全部改动在新分支 `feat/ten-stage-router` 上
- 回滚：`git reset --hard e203e43` + 删除未跟踪文件
- 实体同步前自动备份到 `~/.agents/skill-backups/`

## 七、风险与不做的事

**风险**
- 十段比五工位复杂，用户可能不知道从哪进 → 缓解：`studio.py status` 永远显示「建议入口」一句
- 七目录层级加深，路径变长 → 缓解：所有命令支持项目根 + 自动解析
- 兼容层长期存在 → 缓解：在 `studio.py` 顶部注释标明兼容层与移除条件

**不做**
- 不做 Web UI（v2.0.0 决策仍成立）
- 不做平台 API 调用
- 不把对方 9 个 skill 全部搬入（他们的 film-synopsis 等与 onlyshot-drama 职责重叠，只吸收方法与模板）
- 不改画风、运镜、提示词工艺的既有判定
