# project-info · AI-Short-Drama-Studio（三节索引）

> 本文件=工作区导航索引（索引式，不复制技能正文）。开工按「任务关键词 → 锚词 → 文件」定位再读，不盲扫全仓（细则 #275/#276）。

## 一、架构

技能包三段式：主入口 `SKILL.md`（触发示例 72 类 / 十段弹性路由双形态 / 四种入口模式 / 对标参考流程 / 铁律与核心公式 / 平台硬约束 / 成本纪律 / 排障速查 / 项目层多集）→ `references/` 28 篇按需加载工艺文档（含 stage-router 十段路由总纲、concept-anchor 概念三路径、worldbuilding-rules 世界观规则、treatment-audit 分场审计与剧本融合、performance-craft 表演五支柱、review-rubric 审查规则表、novel-adaptation 原著改编）→ `scripts/` 32 个工程脚本（含 task_ledger 任务台账、impact_graph 改稿影响面、estimate_cost 成本估算、measure_ref 对标测量、review_check 审查记录、novel_index 原著索引、check_skill 技能自身体检、migrate_storyboard 分镜迁移、add_toc 目录维护、run_trigger_eval 触发评测）。数据流：用户素材（完整剧本 / 一句话梗概 / 长篇小说）→ 工作室项目（`studio.py init`：`studio.json` + 七目录 + 三份控制文件 + `场景板/` + 各集集级子目录；`--novel` 时另建 `_novel/index.json`）→ 十段推进（01 概念 → 02 角色 → 03 世界观〔可选〕→ 04 分场 → 05 剧本融合 → 06 资产 → 07 表演〔可选〕→ 08 分镜提示词〔技法 A 分镜智能体 / 技法 B 宫格直生〕→ 09 出片 → 10 后期发布）→ 门禁串联（`studio.py check`：`check_script` / `validate_storyboard` / `check_refs` / `manifest verify`（含提示词哈希）/ `check_scene_plates` / `lint_prompt`）→ 成片与发布包装。旁路记录：`_tasks.jsonl` 任务台账（成本）、`_impact.json` 依赖图（改稿影响面）、`_reviews/` 审查记录。布局兼容：v2 旧项目（根下 `第X集/{剧本.md,分镜/,成片/}` + `素材/`）由 `studio.py` 的 `detect_layout` 自动判别，不迁移。本工作区（git 仓库）为开发源；发布面=GitHub；使用面=本机技能实体（静态复制，`scripts/sync_entity.py` 一键同步）。

## 二、目标

把一句话剧情或完整剧本变成可执行的 AI 短剧视频（动态漫/漫剧、写实风等形态通用）；本工作区职责=开发、版本化、发布该技能（当前 v3.0.0）。

## 三、模块表（关键词锚定列）

| 模块 | 载体 | 关键词锚定（3-8） |
|---|---|---|
| 主入口/十段路由 | `SKILL.md` | 十段（概念/角色/世界观/分场/剧本融合/资产/表演/分镜提示词/出片/后期发布）、四种入口、铁律、平台硬约束、排障速查、项目层多集、成本纪律 |
| 路由总纲 | `references/stage-router.md` | 十段定义、全流程/单阶段/接力/修订、最小输入、回退与下游过期、控制文件职责 |
| 概念锚定 | `references/concept-anchor.md` | 三路径判定、C 爆款复合引擎、三层反转链、极速节点、A 三幕要素、B 三层结构法 |
| 世界观规则 | `references/worldbuilding-rules.md` | 规则四问、知识层级表、setup-payoff、能力分布、禁对白倒设定 |
| 分场与剧本融合 | `references/treatment-audit.md` | 场景数估算、逐场四问、六个审计标签、资产扫描单、密度分流、防注水 |
| 表演层 | `references/performance-craft.md` | 五支柱、倾听与反应、身体档案、主档案模板、眼神细节、十五种败笔、五分制 |
| 工作室流程 | `references/studio-workflow.md` | 十段与旧五工位映射、数据契约、改稿回流表、单集推进命令 |
| 工作室总控 | `scripts/studio.py` | init/status/check/board、双形态（drama/short）、detect_layout 双布局、十段扫盘、当前焦点段、改稿时间提示、门禁串联 |
| 短视频工艺 | `references/short-video-studio.md` | 时长预算反推、三档节奏、Hook 六分类、追问四失效、发布包四件、脚本小节结构 |
| 短端口播机检 | `scripts/short_plan.py` | 口播字数区间、单镜≥1.5s、时间轴断档、钩子小节、发布包三件、`--target` 预算反推 |
| 分镜智能体（08 段技法A） | `references/agent-prompt.md` | 系统提示词、镜号、时长、转场、声音设计、尾帧接力 |
| 宫格分镜（08 段技法B） | `references/grid-storyboard.md` | 4/6/9/25 宫格、分镜JSON、直生15s、拼图 |
| 人脸审核规避（06 段技法） | `references/face-workarounds.md` | 墨镜遮挡、网格遮挡、无五官三视图、服装+头部、风格转绘 |
| 素材一致性工艺 | `references/asset-workflow.md` | 人物锚点法、ref红线、候选图选择、重构图、首帧四要素 |
| 分镜图工艺 | `references/frame-industrial.md` | 三层分离、8段式、4模选档、并发限流、非人形偏置 |
| 提示词进阶 | `references/prompt-craft.md` | 三作用域、末态法则、多素材绑定、否定失效、实测档案 |
| 运镜语法 | `references/camera-grammar.md` | 运镜三参数、模型值vs设计值、情绪化运镜十式、视角层级、特殊场景参数、自查四问 |
| 画风词典 | `references/visual-lexicon.md` | 画风三层、十种画风写法、转写对照、光影三件套、场景风格统一、背景六段式 |
| 角色设定卡 | `references/character-design.md` | 设定卡七段、跨镜五维审查、三类漂移成因、复用边界 |
| 发布投放 | `references/publish-ops.md` | 三平台差异、字幕封面参数、情绪调色、发布前六查、发布后三指标、迭代纪律 |
| 衔接与后期 | `references/transition-editing.md` | 转场做or剪、编辑四件套、延长、集间延长、ffmpeg落地 |
| 连续性台账 | `references/continuity-log.md` | 连续性账、段缝衔接、Take记录、版本账、证据分级 |
| 面部表演 | `references/facs-micro-expression.md` | 微表情四区、真假笑、强度三档、情绪配方 |
| 情绪与钩子 | `references/emotion-beat-curve.md` | 12 节拍曲线、钩子模式库、2 秒结构 |
| 打戏预演 | `references/action-previs.md` | R1-R3 强度档、11 环动力链、镜头五要素 |
| 声音与配音 | `references/audio-voice.md` | 四轨设计、角色音色表、VoiceStudio 自建音色（克隆/设计）、profile_id、Edge TTS 降级、混音检查 |
| 配音合成 | `scripts/tts_voice.py` | 标注稿解析、profile_id、/v1/audio/speech、studio.json voices、逐段 mp3、dry-run、list-voices |
| 即梦实测档案 | `references/jimeng-seedance-2.5.md` | Seedance 2.5、素材上限、积分、提示词规则、审核限制 |
| 场景资产 | `references/scene-plates.md` | 场景板、Location/state/View、锁定句、空场与文字政策、反推、验收 |
| 场景板机检 | `scripts/check_scene_plates.py` | 字段、ID/state、政策冲突、光线、敏感词、跨文件引用 |
| 场景单生成 | `scripts/gen_scene_sheet.py` | 数据单源、渲染、verify、docx |
| 分镜 JSON 机检 | `scripts/validate_storyboard.py` | 数量、词数、字符上限、排除词、编号重复、告警、门日志 |
| @引用核对 | `scripts/check_refs.py` | 断链、待补标注、闲置素材、大小写、绑定自检 |
| 剧本机检 | `scripts/check_script.py` | 集号一致、模板占位、@引用清单、钩子与收尾、场次编号、台词时长预算 |
| 多集脚手架 | `scripts/init_project.py` | 多集目录、幂等、扩容 |
| 拼宫格 | `scripts/make_grid.py` | 拼图、4/6/9/25、Pillow、递归扫描 |
| 旧版归档 | `scripts/archive_old_docx.py` | 交付版本管理、_旧版归档、dry-run、selftest |
| 实体同步 | `scripts/sync_entity.py` | 备份、差异扫描、md5 复核、dry-run、prune |
| 双根核对 | `scripts/check_double_root.py` | 双根部署、硬链、samefile、补链、fix |
| 接缝量化检测 | `scripts/check_seams.py` | 尾帧/首帧、SSIM、亮度差、色相差、饱和差、运动持续性、综合偏差、两种模式 |
| docx 分页修复 | `scripts/fix_table_pagination.py` | 表格不跨页、表头重复、防孤行、操作顺序段、keepLines |
| 代码块样式 | `scripts/style_code_blocks.py` | 底纹、左边框、Consolas、keepLines、pPr 顺序、dry-run |
| 一键验收管道 | `scripts/qa_batch.py` | 接缝量化、同源核对、底账、json、ffmpeg 跳过 |
| 生成清单 | `scripts/manifest.py` | init/set/verify、同源、版本分布、定稿核对 |
| 统一裁切 | `scripts/trim_clips.py` | 整拍时长、5.000 秒、帧精确、流复制、干跑 |
| 分镜拼接成片 | `scripts/concat_clips.py` | 参数一致性、流复制拼接、切点导出、异参数重编码、干跑、apply |
| 版本生成引擎 | `scripts/gen_script.py` | 单引擎、数据文件、命中数拦截、verify 回放、all 回归 |
| 任务台账与成本 | `scripts/task_ledger.py` | submit/result/cancel、recover 只查不重生成、report 已花与浪费、_tasks.jsonl 事件溯源 |
| 改稿影响面 | `scripts/impact_graph.py` | 素材→镜→段索引、query 重出清单、成片重剪推导、_impact.json 派生、与 check_refs 同源 |
| 成本前置估算 | `scripts/estimate_cost.py` | 镜数×单价、重试余量、未知档位报错、常量与文档不漂移断言 |
| 对标测量器 | `scripts/measure_ref.py` | probe 时长/切点/镜长、diff 同一把尺、无原片拒绝、ffmpeg 场景检测 |
| 审查规则表 | `references/review-rubric.md` | 五范围 27 条、四档结论、每条指脚本或人工判定、审查记录格式 |
| 审查记录机检 | `scripts/review_check.py` | 结论自洽、每条有证据、PROVISIONAL 写明缺口、空壳检测 |
| 原著结构索引 | `scripts/novel_index.py` | 章节切分、情节点 quote+offset 回查、分集区间、创作词黑名单 |
| 原著改编职责 | `references/novel-adaptation.md` | 与 onlyshot-drama 切分、能做什么/不能做什么、验收要点 |
