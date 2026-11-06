# 项目级 Agent 规则 · AI-Short-Drama-Studio

> 本文件是 **DeepSeek Harness（DSH）项目级指令**：DSH 从项目根读取 `AGENTS.md`（项目根=最近含 `.git` 的祖先目录）并在每会话注入（`@deepseek-ai/dsh-agent-instructions`）。只管「本项目特有信息 + 承载指针」，通用义务不复述（单一权威=用户全局指令链与技能 SKILL.md）。本工作区自 zcode 工作区复制而来，2026-11-06 起按 DSH 口径维护。

## 回指（强制字段）
- 完整纪律（判级/红线/必问/开工四步/GATE/检索端口）权威=shisan-xinuo-workflow SKILL.md；按需以 Skill 工具加载「shisan-xinuo-workflow」（注册名），本文件在场但 Skill 未在场 → 先加载再继续。若本机配置了 DSH 用户全局指令链（`~/.dsh/AGENTS.md` → `~/.agents/AGENTS.md`，DSH 每会话先注入），其纪律优先。
- 会话末：更新 `memory/agent-log.md`（流水区+状态段）后离开——不更新=交接断链。

## 迷你流程骨架（全局纪律缺席时的最小执行序）
- 开工四步：复述 → 承载检查 → 记忆对齐（读 agent-log 状态段一屏）→ 判级（L1 直做 / L2 记录做 / L3 先问）。
- 每轮首产物=复述（新任务全量三行；追加/继续一行）；状态行 `Context: state=… L=… confirm=…`。
- 收尾：GATE 单行 12 字段；agent-log 流水一行+状态段刷新。
- 红线三条：密钥绝不落盘｜重大改动先回滚点｜不假实现（未验证显式标注）。

## 项目纪律（本项目特有）
- **仓库定位**：公开技能仓库——发布物=技能本体（`SKILL.md` / `references/` / `scripts/` / `README.md` / `LICENSE`）；`memory/` 为本地承载（已从版本控制排除），`docs/` 为开发导航。
- **版本与提交**：版本号以 `SKILL.md` front-matter `version` 为准（历史变更记 `SKILL.md` 的「更新记录」节，不再单独维护 CHANGELOG 文件）；提交遵守仓库惯例 `<类型>(<范围>):〈动词开头描述〉`（如 `feat(skill): v1.6.0 …`，类型前缀跟随历史 feat/fix/docs/refactor/chore）；push=对外发布（L3，须用户确认）。
- **验证基线**：改动技能后跑二十二脚本自检 `python scripts/validate_storyboard.py --selftest`（另二十一件 check_refs/init_project/make_grid/archive_old_docx/sync_entity/check_double_root/check_seams/fix_table_pagination/style_code_blocks/qa_batch/manifest/trim_clips/concat_clips/gen_script/check_scene_plates/gen_scene_sheet/lint_prompt/studio/short_plan/tts_voice/dsh_link 同法）全过再提交；`make_grid.py` 需 Pillow，`check_seams.py` 需 numpy/Pillow（实景抽帧另需 ffmpeg，无则跳过），`style_code_blocks.py` 需 python-docx。CI（`.github/workflows/selftest.yml`）在 push 时自动跑同样二十二件 + `examples/demo-multi-ep/` 端到端回归（qa_batch/trim_clips/concat_clips 在无 ffmpeg 环境自动跳过实拍部分；tts_voice 的 selftest 不联网，只有实跑合成才需要本地 VoiceStudio）。
- **DSH 适配（2026-11-06）**：DSH 技能根按 rank 扫描（官方 `@deepseek-ai/dsh-skill-filesystem`）：100 `<项目根>/.dsh/skills` → 200 `<项目根>/.agents/skills` → 300 `customSkillDirs` → 400 `~/.dsh/skills`（`$DSH_HOME/skills`）→ 500 `~/.agents/skills`（`$DSH_AGENTS_HOME/skills`，zcode 共用），发现深度一层（`<根>/<技能名>/SKILL.md` 或 `<根>/<技能名>.md`），同名按 rank 取小。开发期用 `python scripts/dsh_link.py install` 在 `.dsh/skills/ai-short-drama-studio` 建指向本仓库根的目录联接（Windows junction / POSIX symlink），DSH 即加载**本工作区实时技能**（rank 100 压过用户根静态副本）；`.dsh/` 不入库，`status` / `uninstall` 同脚本，用户级安装用 `--root user` 写 `~/.dsh/skills`（rank 400）。改 `SKILL.md` front-matter 后 DSH 自动刷新目录，无需重启。
- **技能实体同步面（DSH 口径；zcode 不受影响）**：本工作区=开发源；发布后同步用 `python scripts/sync_entity.py <实体目录>` 一键完成——备份（默认落 `~/.dsh/skill-backups`，`--backup-dir` 可改）→ 差异扫描 → 同步 → md5 复核；`--dry-run` 预演；排除项=承载与仓库级资产（AGENTS.md/docs/memory/.github/examples/.git/__pycache__/.dsh，列表维护在脚本顶部 EXCLUDE 常量）。DSH 用户根=`~/.dsh/skills/ai-short-drama-studio`（rank 400，DSH 自有，可作同步目标）。`~/.agents/skills/ai-short-drama-studio`（rank 500）为 zcode 与本机共用的静态副本，**本工作区不写入**，以兑现「不影响 zcode 上的文件」。历史上曾为 zcode/`.agents` 双根硬链部署，`check_double_root.py` 已改用 DSH 双根（项目 `.dsh`↔`.agents`、用户 `.dsh`↔`.agents`，zcode 旧根仅兜底），仅需要时手动跑。
- **v2.6.0 DSH 适配（2026-11-06）**：新增 `scripts/dsh_link.py`（项目/用户 DSH 技能根目录联接安装、状态、卸载；Windows junction / POSIX symlink；selftest 覆盖幂等、拒覆盖真实目录、dry-run、卸载不伤源）；`check_double_root.py` 默认双根改 DSH 口径并跳过 `.dsh` 防联接递归；`gen_scene_sheet.py` 查 article-format 时优先 `~/.dsh/skills`；`sync_entity.py` 排除 `.dsh`、备份默认改 `~/.dsh/skill-backups`；`.gitignore` 以 `.dsh/` 替换 zcode 旧 `.v2c/`；删除 zcode 残留 `.v2c/` 与过期 `docs/rename-local-dir.md`；README/AGENTS/SKILL/project-info/CI 二十二脚本口径同步。
- **v2.5.0 工艺词典层（2026-11-01）**：资源包（31 份漫剧提示词资料）深读后补四篇 references——`camera-grammar.md`（运镜三参数：起点景别/终点景别/耗时，模型用值与设计自用值分离，情绪化运镜十式、视角层级、九类特殊场景）、`visual-lexicon.md`（画风三层：线条/上色/色板，十种画风写法、画风词转写对照、光影三件套与六种情绪光、背景六段式）、`character-design.md`（设定卡七段、跨镜五维审查）、`publish-ops.md`（三平台差异、字幕封面参数、情绪调色、发布前六查、发布后三指标与归因顺序）。`lint_prompt.py` 新增运镜三参数缺失告警（selftest 加一项）。**吸收原则**：资源包通篇堆 8K/电影感/超精细，与本项目空词 FAIL 判定正面冲突，故只取其结构与参数、弃其空词；已有更严格规定处（分镜组、镜头连续性、否定三改法、三层工艺分离）只补强不替换。
- **v2.1.0 双形态（2026-10-27）**：新增短视频形态（`studio.py init --form short`）、`scripts/short_plan.py` 口播时长预算机检、`references/short-video-studio.md` 短片工艺；通用机制四条（单镜 1.5s 下限 / 否定配正向清单 / 追问四失效防御 / 发布包装属交付）进铁律，两种形态共用。实体同步状态以 `python scripts/sync_entity.py --dry-run <目标>` 实测为准，不以文档陈述为准。
- **v2.0.0 工作室化重构（2026-10-27）**：骨架由「三路线」改为「五工位流水线」，新增 `references/studio-workflow.md` 与 `scripts/studio.py`（init/status/check/board）；视觉规格留档 `docs/design-specs/studio-board.md`。
- 权威源顺序：DSH 用户全局指令链（若配置：`~/.dsh/AGENTS.md` → `~/.agents/AGENTS.md`）→ shisan-xinuo-workflow SKILL.md → 本文件 → `docs/project-info.md`。

## 项目承载（已就绪）
- `memory/agent-log.md`：一档制四区（状态段/教训区/偏好段/流水区；本地留档，不入库）。
- `docs/project-info.md`：六节索引（模块表带关键词锚定列，细则 #275）。
