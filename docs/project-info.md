# project-info · AI-Short-Drama-Studio（三节索引）

> 本文件=工作区导航索引（索引式，不复制技能正文）。开工按「任务关键词 → 锚词 → 文件」定位再读，不盲扫全仓（细则 #275/#276）。

## 一、架构

技能包三段式：主入口 `SKILL.md`（触发示例 37 类 / 五工位流水线双形态 / 对标参考流程 / 铁律与核心公式 / 平台硬约束 / 成本纪律 / 排障速查 / 项目层多集）→ `references/` 16 篇按需加载工艺文档 → `scripts/` 19 个工程脚本。数据流：用户素材（完整剧本 / 一句话梗概）→ 工作室项目（`studio.py init`：`studio.json` + `素材/` + `场景板/` + 各集三件）→ 五工位推进（剧本台 → 角色与场景台 → 分镜台〔技法 A 分镜智能体 / 技法 B 宫格直生〕→ 出片台 → 后期台）→ 门禁串联（`studio.py check`：`validate_storyboard` / `check_refs` / `manifest verify` / `check_scene_plates`）→ 成片与发布包装。改稿按层回流，`studio.py status` 用文件时间给出「资产晚于成片」「分镜晚于视频段」提示。本工作区（git 仓库）为开发源；发布面=GitHub；使用面=本机技能实体（静态复制，`scripts/sync_entity.py` 一键同步）。

## 二、目标

把一句话剧情或完整剧本变成可执行的 AI 短剧视频（动态漫/漫剧、写实风等形态通用）；本工作区职责=开发、版本化、发布该技能（当前 v2.1.0）。

## 三、模块表（关键词锚定列）

| 模块 | 载体 | 关键词锚定（3-8） |
|---|---|---|
| 主入口/五工位 | `SKILL.md` | 对标流程、五工位（剧本台/角色与场景台/分镜台/出片台/后期台）、铁律、平台硬约束、排障速查、项目层多集、成本纪律、首镜2秒钩子 |
| 工作室流程 | `references/studio-workflow.md` | 五工位定义与门禁、studio.json 数据契约、改稿回流表、单集推进命令 |
| 工作室总控 | `scripts/studio.py` | init/status/check/board、双形态（drama/short）、扫盘进度、当前焦点工位、改稿时间提示、门禁串联 |
| 短视频工艺 | `references/short-video-studio.md` | 时长预算反推、三档节奏、Hook 六分类、追问四失效、发布包四件、脚本小节结构 |
| 短端口播机检 | `scripts/short_plan.py` | 口播字数区间、单镜≥1.5s、时间轴断档、钩子小节、发布包三件、`--target` 预算反推 |
| 分镜智能体（分镜台技法A） | `references/agent-prompt.md` | 系统提示词、镜号、时长、转场、声音设计、尾帧接力 |
| 宫格分镜（分镜台技法B） | `references/grid-storyboard.md` | 4/6/9/25 宫格、分镜JSON、直生15s、拼图 |
| 人脸审核规避（角色台技法C） | `references/face-workarounds.md` | 墨镜遮挡、网格遮挡、无五官三视图、服装+头部、风格转绘 |
| 素材一致性工艺 | `references/asset-workflow.md` | 人物锚点法、ref红线、候选图选择、重构图、首帧四要素 |
| 分镜图工艺 | `references/frame-industrial.md` | 三层分离、8段式、4模选档、并发限流、非人形偏置 |
| 提示词进阶 | `references/prompt-craft.md` | 三作用域、末态法则、多素材绑定、否定失效、实测档案 |
| 衔接与后期 | `references/transition-editing.md` | 转场做or剪、编辑四件套、延长、集间延长、ffmpeg落地 |
| 连续性台账 | `references/continuity-log.md` | 连续性账、段缝衔接、Take记录、版本账、证据分级 |
| 面部表演 | `references/facs-micro-expression.md` | 微表情四区、真假笑、强度三档、情绪配方 |
| 情绪与钩子 | `references/emotion-beat-curve.md` | 12 节拍曲线、钩子模式库、2 秒结构 |
| 打戏预演 | `references/action-previs.md` | R1-R3 强度档、11 环动力链、镜头五要素 |
| 声音与配音 | `references/audio-voice.md` | 四轨设计、角色音色表、Edge TTS、混音检查 |
| 即梦实测档案 | `references/jimeng-seedance-2.5.md` | Seedance 2.5、素材上限、积分、提示词规则、审核限制 |
| 场景资产 | `references/scene-plates.md` | 场景板、Location/state/View、锁定句、空场与文字政策、反推、验收 |
| 场景板机检 | `scripts/check_scene_plates.py` | 字段、ID/state、政策冲突、光线、敏感词、跨文件引用 |
| 场景单生成 | `scripts/gen_scene_sheet.py` | 数据单源、渲染、verify、docx |
| 分镜 JSON 机检 | `scripts/validate_storyboard.py` | 数量、词数、字符上限、排除词、编号重复、告警、门日志 |
| @引用核对 | `scripts/check_refs.py` | 断链、待补标注、闲置素材、大小写、绑定自检 |
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
| 版本生成引擎 | `scripts/gen_script.py` | 单引擎、数据文件、命中数拦截、verify 回放、all 回归 |
