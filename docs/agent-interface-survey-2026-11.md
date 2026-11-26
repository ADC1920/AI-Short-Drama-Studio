# Agent 调用面深度调研（2026-11-26）

> 调研目标：找出 GitHub 上与本项目相似或更深度的公开项目，定位可融合升级点，让本技能更适合 agent 调用。
> 与前三份调研的分工：`ecosystem-survey-2026-10.md`（同类技能包横向比对）、`ecosystem-survey-2026-10-short-video.md`（短视频赛道）、`optimization-survey-2026-11.md`（产品与工程缺口）都不看「agent 怎么可靠调用这台机器」。本轮只补这一个维度，不重复已实施项。
> 方法：本仓 28 脚本逐一实测（退出码直取不经管道）+ 官方规范逐条比对 + 两个子代理深读四个高星仓库源码。
> 本文只是调研结论，不含实施；实施另行走版本流程。

## 一、结论速览

项目在「技能内容深度」上已经领先（28 脚本全带 selftest、成片级量化他处没有），但在「让 agent 可靠调用」这一层是明显短板：**机读能力只覆盖 10/28 脚本，退出码语义未契约化，并有 3 个实测可复现的缺陷**。这些不是功能缺失，是「同一套能力 agent 用不顺」的接口问题，改造成本低、收益直接。

| 优先级 | 项 | 性质 | 实测证据 | 工作量 |
|---|---|---|---|---|
| **P0-1** | `studio.py status --json` 崩溃 | 缺陷 | `TypeError: WindowsPath is not JSON serializable` | 小 |
| **P0-2** | 两处假绿退出码 | 缺陷 | 无参调用 exit=0 但什么都没检查 | 小 |
| **P0-3** | 分镜契约缺 scene 关联，无覆盖对账 | 契约缺口 | 分镜只有 `shot_number`+`prompt_text` | 中 |
| **P1-4** | 退出码契约缺失，3/4 各有三义 | 接口 | `task_ledger:157` 的 3 = 不要重试 | 小 |
| **P1-5** | 18 个脚本无 `--json` | 接口 | 只有 10/28 有机读 | 中 |
| **P1-6** | `check --json` 返回文本而非 findings | 接口 | `output` 是截断字符串 | 中 |
| **P1-7** | `SKILL.md` front-matter 的 `version` 违反官方白名单 | 规范 | 官方 `quick_validate.py` 判 FAIL | 小 |
| **P2-8** | 20 个 reference 无 TOC | 规范 | 全部 >100 行文件都没有 | 小 |
| **P2-9** | 更新记录占 39.9% 字符 | 结构 | 17,997 / 45,066 字符 | 小 |
| **P2-10** | 无 eval / 触发评测 / 打包分发 | 能力 | 官方 skill-creator 有完整一套 | 大 |

## 二、实测缺陷（可直接复现）

### P0-1 `studio.py status --json` 崩溃

```bash
python scripts/studio.py status examples/demo-multi-ep --json
# exit=1
# TypeError: Object of type WindowsPath is not JSON serializable
```

根因在 `scripts/studio.py:388-389`：

```python
"prompts": [p for p in sorted(u["prompts"].glob("*.md"))
            if doc_ready(p)] if u["prompts"].is_dir() else [],
```

`p` 是 `Path` 对象，直接进了 dict。同函数里 `storyboard` 与 `plates` 两行已正确写 `str(p.relative_to(root))`——**同一处代码，两种写法**，说明是遗漏而非设计。

触发条件：`episodes_detail[].prompts` 或 `.acting` 非空。v2 布局下 `u["prompts"]` 指向集目录本身，`剧本.md` 一存在即命中；v3 布局下 `06_prompts/第N集/*.md` 有真提示词稿即命中。**两种布局都会炸**（已分别复现）。

严重性：agent 最需要的机读入口（进度 + 焦点段 + 成本视图）完全不可用。人类可读路径正常，所以人工点一遍发现不了。

**为什么 28/28 selftest 全绿却没抓住**：`studio.py` 的 selftest 有 20+ 处 `collect()` 与 `print_status()` 调用，**没有任何一处对 `collect()` 结果做 `json.dumps()` 断言**。门禁缺「JSON 可序列化」这条不变量。

### P0-2 两处假绿退出码

```bash
python scripts/check_scene_plates.py  → exit 0（打印 help，一项没查）
python scripts/gen_scene_sheet.py     → exit 0（同上）
```

对照实测：`estimate_cost` / `check_seams` / `qa_batch` / `short_plan` / `check_refs` / `check_script` / `lint_prompt` / `validate_storyboard` / `init_project` / `make_grid` / `trim_clips` / `concat_clips` / `gen_script` / `tts_voice` / `review_check` / `studio` / `archive_old_docx` / `sync_entity` / `check_double_root` / `fix_table_pagination` **全部返回 2**。这两处是孤立偏离。

定位：`scripts/check_scene_plates.py:333-334`、`scripts/gen_scene_sheet.py:310-311`，都是 `ap.print_help()` 后跟裸 `return`（Python 里等于 `return None` → exit 0）。

严重性：agent 用 `exit == 0` 判绿时会**把「根本没跑」当成「检查通过」**。项目自己的「管道判绿=假绿」纪律管的是 shell 管道，管不到工具自身假绿。

### P0-3 分镜契约缺 scene 关联，无覆盖对账

实测 `examples/demo-multi-ep/第1集/分镜/sb.json` 的镜头字段只有：

```json
{"shot_number": "1", "prompt_text": "大远景，暴雨夜荒野，@破败茶棚 孤立雨中…"}
```

`validate_storyboard.py` 的检查项（C1-C10）全部是**分镜自身**的：数量、词数、字符上限、排除词、编号重复、否定词根、并列主体、抽象形态。**没有一项回答「分镜是否覆盖了剧本的全部场景」**。

后果：剧本写了 10 场，分镜只做了 6 场，所有机检照样全绿。而且因为没有 `scene_id` 字段，想做这个对账**在数据层就没有可对的锚点**——不是校验器漏了，是契约里没这个字段。

对照 `moyin-creator` 的 `Shot` 契约有 `sceneRefId/sceneId/sceneViewpointId` 三件套，`aid-studio` 用 `{scenes:[{sceneName, shots:[...]}]}` 信封把场景与镜头显式嵌套，`shuohao-skills` 用「节拍认领」（每镜声明覆盖剧本某场的 `[起,止]` 节拍区间，要求每个节拍恰好被一个镜头认领）。三家都做了，方向一致。

## 三、接口层缺口

### P1-4 退出码未契约化，且 3/4 各有三义

全仓静态统计：`0` 70 处 / `1` 21 处 / `2` 88 处 / `3` 3 处 / `4` 3 处。0/1/2 大体是「通过 / 检查不通过 / 用法错」，但没有写成任何文档。

退出码 3 的三处互相冲突：

| 位置 | 语义 | agent 该做什么 |
|---|---|---|
| `task_ledger.py:157` | 已有运行中任务，拒绝重复提交 | **不要重试**；先 result/cancel，或 `--force`（可能重复计费） |
| `novel_index.py:268` | 内部断言失败 | 上报，不重试 |
| `concat_clips.py:198` | 拼接参数不一致，拒绝执行 | **不要重试**；统一参数或加 `--reencode-mismatch` |

**核心风险**：agent 若按「3 = 可重试的临时错误」处理，在 `task_ledger` 场景会**重复计费**。

另外 4 个 argparse 子命令型脚本（`impact_graph` / `novel_index` / `task_ledger` / `measure_ref`）无参时打印 usage 后 exit 0，agent 用「exit==0 = 成功」会误判「没执行子命令」为成功。

### P1-5 `--json` 只覆盖 10/28

有：`check_scene_plates` / `check_seams` / `estimate_cost` / `qa_batch` / `short_plan`（顶层）+ `studio`（`status`/`check` 子命令）+ `impact_graph` / `novel_index` / `task_ledger` / `measure_ref`（子命令级）。

无：`check_refs` / `check_script` / `lint_prompt` / `validate_storyboard` / `review_check` / `manifest` / `concat_clips` / `trim_clips` / `init_project` / `make_grid` / `gen_scene_sheet` / `gen_script` / `archive_old_docx` / `fix_table_pagination` / `style_code_blocks` / `sync_entity` / `check_double_root` / `tts_voice`（18 个）。

其中 `check_refs` / `check_script` / `lint_prompt` / `validate_storyboard` 是**最核心的四个门禁**，全都没有机读输出——agent 只能靠正则解析中文散文。

### P1-6 `studio.py check --json` 返回文本而非 findings

实测结构：

```json
{
  "project": "<绝对路径>",
  "results": [
    {"name": "validate_storyboard 第1集\\分镜\\sb.json",
     "ok": true, "exit": 0,
     "output": "<子进程 stdout 原文，尾部截断 1200 字符>"}
  ],
  "ok": true,
  "warnings": []
}
```

四个问题：
1. `output` 是字符串不是 `findings[]`，agent 还得二次解析，且取的是 `output.strip()[-1200:]`（**尾部**截断，头部规则信息可能已被切掉）。
2. `name` 里混 Windows 反斜杠路径。
3. 无 `rule_id` / `line` / `severity` / `fix_hint`。
4. `warnings` 是自由文本数组。

### P1-7 `version` 键违反官方 front-matter 白名单

官方 `anthropics/skills`（20 万星）的 `skill-creator/scripts/quick_validate.py` 定义：

```python
ALLOWED_PROPERTIES = {'name', 'description', 'license', 'allowed-tools', 'metadata', 'compatibility'}
```

本项目 front-matter 有 `version: 3.0.0`，**不在白名单内**，用官方脚本会直接 `Unexpected key(s) in SKILL.md frontmatter: version` → exit 1。官方 20+ 个技能全部不写 `version` 顶层键。

项目级规则又要求「版本号以 `SKILL.md` front-matter `version` 为准」，不能删。已验证的兼容改法：

```yaml
metadata:
  version: 3.0.0
```

顶层键变成 `{name, description, license, metadata}`，完全合规，版本仍可机读。

### 重复入口

同一需求两条命令都能做，参数名还不一致：

- `SKILL.md:128` 教 agent 用 `impact_graph.py query --asset @顾寒`
- `README.md:67` 教 `studio.py status --impact "@顾寒"`
- SKILL.md 主线正文不教 `--impact`

两条都实测可用、结果等价。Anthropic 工具设计指南明确警告「overlapping tools distract agents from pursuing efficient strategies」。

## 四、结构层缺口

### P2-8 20 个 >100 行 reference 全部无 TOC

`agent-prompt`(209) / `performance-craft`(241) / `prompt-craft`(238) / `transition-editing`(226) / `treatment-audit`(176) / `studio-workflow`(172) / `grid-storyboard`(163) / `short-video-studio`(150) / `worldbuilding-rules`(150) / `concept-anchor`(135) / `stage-router`(127) / `frame-industrial`(122) / `review-rubric`(119) / `continuity-log`(118) / `scene-plates`(116) / `camera-grammar`(114) / `asset-workflow`(114) / `audio-voice`(108) / `character-design`(108) / `publish-ops`(106)。

官方最佳实践：「For reference files longer than 100 lines, include a table of contents at the top. This ensures Claude can see the full scope of available information even when previewing with partial reads.」

### P2-9 SKILL.md 更新记录占 39.9% 字符

总 45,066 字符 / 461 行，其中：

| 区块 | 字符 | 占比 |
|---|---|---|
| **更新记录** | **17,997** | **39.9%** |
| 索引表 | 5,721 | 12.7% |
| 01-10 段正文 | 4,940 | 11.0% |
| 触发示例 | 4,061 | 9.0% |
| 铁律 | 2,969 | 6.6% |

更新记录是纯史料（版本演进细节），agent 每次加载 SKILL.md 都会读入这 1.8 万字符。官方要求「No time-sensitive information」+「concise is key」。行数虽然还在 461 < 500 的限内，但字符占比已经失衡。

### P2-10 无 eval / 触发评测 / 打包分发

官方 `skill-creator` 附带完整一套：
- `run_eval.py`：测 description 能否让 agent 正确触发技能
- `aggregate_benchmark.py`：汇总基准
- `improve_description.py`：自动优化 description
- `quick_validate.py`：规范校验
- `package_skill.py`：打包 `.skill` zip
- `eval-viewer/generate_review.py`：结果可视化
- `.claude-plugin/marketplace.json`：插件市场入口

本项目零覆盖。72 条触发话术从未被机检验证过能否真的触发。

## 五、外部参照的机制清单（按可移植性排序）

### 来自 `Emily2040/seedance-2.0`（8,310★，MIT，同为 Agent Skill 包）

1. **`validate_repo.py --list` 单一入口**：打印固定检查计划并按序执行，首错原样传播退出码，CI 调同一入口。本项目 `studio.py check` 已具备雏形，但只串 7 个脚本。
2. **schema + 实例强制**：`schema_check.py` 要求每个 schema 必须在 `validation/schema-instances.json` 里有至少一个实例，新增 schema 无实例即失败。本项目无 JSON Schema 文件。
3. **`strict_json.py`**：拒绝重复键、NaN/Infinity、深度 >128、单文件 >4 MiB；诊断最多 50 条 / 16 KiB。
4. **禁止 fixture 冒充生产结果**：`generation_run_check.py` 要求 `is_synthetic_fixture:true` 的记录必须标 `not_run_fixture`。
5. **禁止装饰性 flag**：`tests/test_strict_cli_contract.py` 断言「声明了 `--strict` 就必须真的多查一项」，否则必须报 `unrecognized arguments`。
6. **「schema alone is never a valid gate」**：明写 Schema 只能证单记录结构，图级血缘必须另跑语义校验器。
7. **「JSON 是机器真相，胶囊由它重建，绝不同时手维护同一事实」**。

### 来自 `shijue-aid/aid-studio`（1,802★）

8. **命名引用占位协议**：LLM 只允许输出 `@图片N[name]`；白名单直接写进 system prompt；落库前 `sanitizeOutputImageReferences` 剥掉白名单外引用；解析失败记 `unresolvedNames` 不静默吞。这正好补本项目 `check_refs.py` 只能事后查断链、管不住 LLM 杜撰引用的缺口。

### 来自 `MemeCalculate/moyin-creator`（4,879★）

9. **分层提示词编译器**：JSON 只存枚举 id（`shotSize:"ms"`），编译期查字典转 token，按固定层序（Camera→Lighting→Subject→Mood→Atmosphere→Setting/Audio→Style→Base→Continuity）拼装；关闭的开关输出**负向显式指令**（`SFX: 禁止音效`）；逐镜字段为空回退项目级 profile。这正是 `shuohao-skills`「程序拼装提示词」的完整实现，本项目 `lint_prompt.py` 只校验不编译。
10. **`SEEDANCE_LIMITS` 硬校验**：≤9 图 / ≤3 视频 / ≤3 音频 / 总 ≤12 / prompt ≤5000 字符。
11. **`bizSeq = parentTaskId*1000000 + slot`**：确定性 take 编号，天然幂等，重入即覆盖同号。

### 来自 `xhongc/ai_story`（2,126★）

12. **补差集续跑**：用 `status='completed'` 反查 `_get_missing_*_ids()`，重跑只处理缺口。
13. **僵尸任务回收**：2 分钟阈值 + 检查活跃任务表。

## 六、不建议做的

- **引入 MCP server / JSON-RPC 层**：`ai_story` 与 `aid-studio` 都做了完整 MCP，但那是平台形态（有常驻服务、数据库、鉴权）。本项目是纯文件 CLI，加 MCP 会把「装好即用」变成「先起服务」，与 v2.0.0 的「不做 Web 前端/平台 API 依赖」决策冲突。**改为把现有脚本的 JSON 输出做扎实**，性价比高一个量级。
- **照搬 `Shot` 的 40+ 字段**：`moyin-creator` 的字段密度建立在 Electron 应用与图形界面上。技能包靠散文指导，字段太多会变成 agent 填表的负担。**只补最关键的 `scene_id` + `shot_size` + `duration` 三个**。
- **引入 JSON Schema 校验框架**：`seedance-2.0` 用 JSON Schema，但那需要额外依赖。本项目是 stdlib 优先，用 Python 断言 + 明确错误消息即可达到同等效果。
- **完整复制 40 条机检规则**：三仓合计规则数远超本项目，但很多是平台特有的（数据库约束、API 配额）。只吸收「纯文本可判定」的部分。

## 七、建议的实施顺序

**第一批（缺陷修复，一天内可完成，风险极低）**
1. 修 `studio.py:385,388` 的 `Path` → `str()`，并在 selftest 加一条 `json.dumps(collect(root))` 断言（这条断言本身就能防住同类回归）。
2. 修 `check_scene_plates.py:334` 与 `gen_scene_sheet.py:311` 的裸 `return` → `return 2`。
3. 把 `version` 挪进 `metadata`。

**第二批（契约化，一到两天）**
4. 新增 `references/cli-contract.md`：把 0-4 的语义、每个脚本用哪个码、3/4 的具体含义写成一张表；SKILL.md 索引表加一行指针。
5. 给 `check_refs` / `check_script` / `lint_prompt` / `validate_storyboard` 四个核心门禁加 `--json`，输出结构统一为 `{ok, findings:[{rule, level, file, line, msg, fix}], summary}`。
6. `studio.py check --json` 的 `results[]` 增加 `findings[]`（子脚本有 `--json` 就解析进来，没有就保留原 `output` 字段向后兼容）。

**第三批（契约扩展，需用户确认，因为改动分镜数据格式）**
7. 分镜 `shots[]` 增加 `scene_id`（必填）与 `shot_size` / `duration`（选填），`validate_storyboard.py` 增加 C11「覆盖对账」：剧本场次集合 ⊆ 分镜 scene_id 集合，缺场即 FAIL 并列出缺哪几场。
8. 老分镜 JSON 无 `scene_id` 时降级为 WARNING 不阻断（向后兼容）。

**第四批（结构优化，可并行）**
9. 20 个 >100 行 reference 加 TOC（可用脚本批量插）。
10. 更新记录迁 `docs/CHANGELOG-skill.md`，SKILL.md 只留一行指针。

**第五批（长线，需评估）**
11. eval 体系：先做最小的「触发评测」——用 72 条话术跑一遍，看 description 能否正确路由。
12. `.claude-plugin/marketplace.json`：让技能可一键安装。

## 八、待用户决策

1. 第三批改分镜契约会动数据格式，是否接受？老项目要不要提供迁移脚本？
2. eval 体系（第五批 11）投入较大（需要真实调用模型、多次重复），是否现在做？
3. `--json` 输出结构是否采纳本文建议的 `{ok, findings[], summary}` 形态，还是保持现有各脚本自由格式？

## 九、来源

- 本仓实测：28 脚本退出码直取（`python scripts/X.py >/dev/null 2>&1; echo $?`，不经管道）；`status --json` / `check --json` 真实输出；`grep -c 'add_argument.*--json'` 精确计数；SKILL.md 字符占比脚本计算。
- 官方规范：`github.com/anthropics/skills`（200,767★，2026-11-16 推送）的 `skills/skill-creator/scripts/quick_validate.py`、`skills/mcp-builder/reference/mcp_best_practices.md`；`platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices`；`anthropic.com/research/writing-tools-for-agents`。
- 外部仓库（均 `gh api` 核实元数据，深读源码）：`Emily2040/seedance-2.0`（8,310★，MIT）、`MemeCalculate/moyin-creator`（4,879★）、`xhongc/ai_story`（2,126★）、`shijue-aid/aid-studio`（1,802★）。
- 前次调研（不重复其结论）：`docs/ecosystem-survey-2026-10.md`、`docs/ecosystem-survey-2026-10-short-video.md`、`docs/optimization-survey-2026-11.md`。
