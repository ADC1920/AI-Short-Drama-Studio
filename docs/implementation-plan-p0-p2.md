# AI-Short-Drama-Studio 能力升级实施方案（P0-1 至 P2-7）

> 编制时点 2026-11-12，基线 v2.7.0。依据 `docs/optimization-survey-2026-11.md` 的调研结论。
> 本文是实施方案，不含已执行的代码改动。每项能力的落地另行走版本流程，按本文的验收用例收口。
> 方案内所有文件路径、函数名、字段名均已对照当前仓库实际代码核实（2026-11-12）。

## 1 总览

### 1.1 方案边界

本方案覆盖七项能力：生成任务台账与成本记账、改稿影响面依赖图、内容质量评估与独立审查、提示词血缘哈希、对标测量器、成本前置估算、上游小说长文分析。

不做的事：不引入数据库、不引入 Web 前端、不自建模型调用层。这三条延续 v2.0.0 的既有决策——技能包保持纯文件、可移植、不绑死平台。所有新增能力以「文件 + Python 脚本 + selftest」形态实现，与现有 22 个脚本同构。

统一设计约束四条：

1. 所有脚本只依赖标准库，除非现有脚本已依赖（Pillow、numpy、python-docx）。新脚本不引入新依赖。
2. 每个新脚本必须带 `--selftest`，且纳入 `.github/workflows/selftest.yml` 的循环清单。
3. 所有新增数据文件用 UTF-8 无 BOM、`\n` 换行，与现有 `manifest.py` 的 `newline="\n"` 保持一致。
4. 所有新增字段对老项目向后兼容：缺失即降级为警告，不阻断。

### 1.2 七项能力一览

| 编号 | 能力 | 新增/改动 | 新增数据文件 | 工作量 | 依赖 |
|---|---|---|---|---|---|
| P0-1 | 生成任务台账与成本记账 | 新增 `task_ledger.py`，改 `studio.py` | `_tasks.jsonl` | 中 | 无 |
| P0-2 | 改稿影响面依赖图 | 新增 `impact_graph.py`，改 `studio.py` | `_impact.json` | 中 | P0-1 的镜号命名 |
| P0-3 | 内容质量评估与独立审查 | 新增 `review-rubric.md`、`review_check.py`、`quality_gate.py` | `_reviews/*.md` | 大 | 无 |
| P1-4 | 提示词血缘哈希 | 改 `manifest.py` | 复用 `_manifest.json` | 小 | 无 |
| P1-5 | 对标测量器 | 新增 `measure_ref.py` | `_refs/<对标名>.json` | 中 | 复用 `check_seams.py` |
| P1-6 | 成本前置估算 | 新增 `estimate_cost.py` | 无（只算不存） | 小 | 复用 P0-1 的单价表 |
| P2-7 | 上游小说长文分析 | 新增 `novel_index.py`、`novel-adaptation.md` | `_novel/index.json` | 大 | 无 |

### 1.3 实施顺序与批次

按依赖关系与风险分三批，每批可独立收口、独立回滚。

| 批次 | 内容 | 理由 |
|---|---|---|
| 第一批 | P1-4、P1-6、P0-1 | 三者都轻、互相配合：哈希给台账提供 prompt 指纹，估算给台账提供预估积分。先做这批，后续两项才有数据基础 |
| 第二批 | P0-2、P1-5 | 都依赖第一批的镜号与台账口径；两者共用 ffprobe 探针代码 |
| 第三批 | P0-3、P2-7 | 都是重投入、都需要真实项目样本校准，放最后 |

每批完成后跑全量 CI（当前 22 项 selftest + 新增项），全绿再进下一批。

### 1.4 统一设计约束的执行方式

新增脚本的骨架统一复用 `manifest.py` 的结构：顶部模块 docstring 写用途与用法、`now()` 时间函数、`load_*`/`save_*` 成对、`cmd_*` 子命令、`selftest()`、`main()` 里 `sys.stdout.reconfigure(encoding="utf-8")`。这样七个新脚本读起来像同一套代码，降低维护成本。

## 2 P0-1 生成任务台账与成本记账

### 2.1 缺口与证据

全仓 grep `retry|resume|checkpoint|断点|续跑|幂等`，唯一命中是 `scripts/init_project.py:12` 的目录幂等，与生成任务无关。全仓 grep `cost|积分|credit|quota|budget|记账`，只在 `scripts/short_plan.py:53` 命中 `def budget(target)`，那是口播字数预算。

`studio.json` 的 `CONFIG_DEFAULTS`（`scripts/studio.py:42`）字段为 schema/form/title/aspect/model/episodes/scene_plate/voices/notes，无成本位。

SKILL.md 的「估算 → 确认 → 记账」三步纪律，第三步「记账」只在对话里写一行，跨会话即失效。

### 2.2 数据契约

新增项目级文件 `<项目>/_tasks.jsonl`，一行一个事件，追加写不覆盖。字段定义：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ts` | string | 是 | `YYYY-MM-DD HH:mm:ss`，与 `manifest.py` 的 `now()` 同格式 |
| `event` | string | 是 | `submit` / `result` / `cancel` |
| `unit` | string | 是 | 集单位，短剧为 `第1集`，短视频为 `single` |
| `shot` | string | 是 | 镜号，取自分镜 JSON 的 `shot_number` 或 `manifest` 的 `shot` |
| `prompt_sha256` | string | submit 必填 | 提示词正文 sha256 前 12 位，与 P1-4 同算法 |
| `model` | string | submit 必填 | 模型标识，如 `seedance-2.5` |
| `est_credits` | number | 否 | 预估积分，来自 P1-6 估算 |
| `actual_credits` | number | result 必填 | 实耗积分，由用户按界面读数填入 |
| `status` | string | result 必填 | `success` / `failed` / `cancelled` |
| `artifact` | string | 否 | 产物相对路径，如 `第1集/分镜/视频段/段01.mp4` |
| `note` | string | 否 | 备注，如重抽原因 |

追加写意味着同一镜号会有多条事件，台账按 `(unit, shot)` 分组、按 `ts` 排序还原状态。这是事件溯源，不是状态快照——好处是不需要加锁，坏处是查询要聚合。

### 2.3 实现

新建 `scripts/task_ledger.py`，五个子命令：

```text
python scripts/task_ledger.py submit <项目> --unit 第1集 --shot 组01 --prompt-sha a1b2c3d4e5f6 --model seedance-2.5 [--est-credits 130] [--force]
python scripts/task_ledger.py result <项目> --unit 第1集 --shot 组01 --status success --actual-credits 130 [--artifact 第1集/分镜/视频段/段01.mp4]
python scripts/task_ledger.py cancel <项目> --unit 第1集 --shot 组01 [--note 内容审核]
python scripts/task_ledger.py recover <项目> [--unit 第1集]
python scripts/task_ledger.py report <项目> [--json]
```

关键函数：

| 函数 | 职责 |
|---|---|
| `append_event(root, event)` | 单行 JSON 追加，校验必填字段 |
| `load_events(root)` | 读全量事件，坏行跳过并计数 |
| `fold_state(events)` | 事件折叠为 `{(unit, shot): {status, attempts, credits, ...}}` |
| `check_duplicate(state, unit, shot, force)` | 有 `pending` 状态且未 `--force` 时拒绝 |
| `cmd_recover` | 只读：列 `pending` 超时项，绝不写盘 |
| `cmd_report` | 汇总：本集已花、失败重抽耗掉多少、预估剩余 |

`fold_state` 的折叠规则：最后一条 `result` 或 `cancel` 决定终态；有 `submit` 无 `result` 即 `pending`；`failed` 后再 `submit` 则 `attempts` 加一，`failed` 的积分计入 `wasted_credits`。

### 2.4 与现有脚本的对接

`studio.py` 加两处改动，不改 `collect()` 的返回结构（避免破坏 `board` 渲染与 `--json` 消费者）：

1. 新增 `cost_summary(root)` 函数，读 `_tasks.jsonl`，返回 `{spent, wasted, pending, by_unit}`。
2. `collect()` 返回值增加一个 `"cost"` 键。老项目无 `_tasks.jsonl` 时该键为 `None`，`print_status` 判空后不显示该节。

`print_status` 增一节输出，形如：

```text
成本：已花 1300 分 · 失败重抽 260 分（占 20%）· 待回执 2 镜
```

`run_check` 不串入 `task_ledger`——台账不是门禁，是账本。违例（有 pending 超时）作为警告列在 `status` 里，不让 `check` 失败。

### 2.5 验收用例

| 用例 | 前置 | 预期 |
|---|---|---|
| 基本记账 | 空项目，submit 后 result success | `report` 显示已花等于 actual_credits，wasted 为 0 |
| 失败重抽 | submit/result failed，再 submit/result success | `attempts` 为 2，`wasted_credits` 等于失败那次积分，已花只算 success |
| 重复提交拦截 | submit 后未 result，再次 submit 同镜 | 非零退出，提示已有 pending；加 `--force` 放行 |
| 只读恢复 | 存在 pending，断网跑 `recover` | 列出 pending 镜号，文件 mtime 不变，新增事件数为 0 |
| 坏行容错 | 手工插入一行非 JSON | 其余事件正常读取，`report` 输出坏行计数警告 |
| 老项目兼容 | 无 `_tasks.jsonl` | `studio.py status` 正常，成本节不显示，退出码 0 |

selftest 覆盖上表六条，其中「失败重抽」用断言锁死不变量：`spent == sum(actual_credits where status == success)`。

### 2.6 风险与回滚

主要风险是用户嫌记两笔（预估与实耗）麻烦，台账最后变空文件。缓解：`submit` 的 `--est-credits` 设为可选，`result` 只要求 `actual-credits`；估算由 P1-6 自动填，用户只在结果时抄一个数。

回滚方式：删 `scripts/task_ledger.py`、还原 `studio.py` 的两处改动、删项目里的 `_tasks.jsonl`。三者互不牵连，因为台账只是旁路记录，不参与任何门禁判定。

## 3 P0-2 改稿影响面依赖图

### 3.1 缺口与证据

`studio.py` 的 `impact_warnings`（约 300 行处）只做两件事：比 `素材/`、`场景板/` 最新 mtime 与 `成片/` 最早 mtime；比分镜目录最新 mtime 与 `视频段/` 最早 mtime。命中就给一句「可能过期」。

而项目手里已有三份可用的依赖数据：

1. `check_refs.py:33` 的 `REF_RE = re.compile(r"@([A-Za-z0-9_\-\u4e00-\u9fff]+)")` 能抽每镜的 @引用名。
2. `check_scene_plates.py:220` 的 `re.findall(r"S-\d{2,}(?:@[a-z0-9][a-z0-9-]*)?", script_text)` 能抽 S-* 引用。
3. `_manifest.json` 每段记 `shot`、`file`、`refs`、`scene_state`，`manifest.py:110` 的 `list` 已能按段列出。

三份数据一拼就能算出精确的「改了素材 A → 哪些镜 → 哪些段」，现在没用。

### 3.2 数据契约

新增 `<项目>/_impact.json`，由 `impact_graph.py build` 生成，是可重建的派生文件（不是事实源）：

```json
{
  "built": "2026-11-12 20:00:00",
  "assets": {
    "@顾寒": {
      "kind": "character",
      "source": "素材/顾寒.png",
      "shots": ["第1集/组01", "第1集/组05"],
      "segments": ["第1集/分镜/视频段/段01.mp4", "第1集/分镜/视频段/段05.mp4"]
    }
  },
  "scenes": {
    "S-01@day-crowd": {"plates": "场景板/场景单.md", "shots": ["第1集/组01"], "segments": ["段01.mp4"]}
  },
  "shots": {
    "第1集/组01": {"prompt_sha256": "a1b2c3d4e5f6", "refs": ["@顾寒", "@奈奈"], "scene_state": "S-01@day-crowd", "segment": "段01.mp4"}
  },
  "orphans": ["@刀疤"]
}
```

`orphans` 记「被引用但素材不存在」的条目，与 `check_refs` 的断链判定同源，用于交叉验证。

### 3.3 实现

新建 `scripts/impact_graph.py`，三个子命令：

```text
python scripts/impact_graph.py build <项目> [--json]
python scripts/impact_graph.py query <项目> --asset @顾寒 [--json]
python scripts/impact_graph.py selftest
```

抽取逻辑不重写正则，直接从 `check_refs.py` 与 `check_scene_plates.py` 导入：

```python
from check_refs import REF_RE, is_ignored, collect_assets
from check_scene_plates import SCENE_REF_RE  # 需先把 220 行的内联正则提为模块级常量
```

`check_scene_plates.py:220` 的正则当前是内联在函数里的，方案要求提为模块级常量 `SCENE_REF_RE`，行为不变，只做可见性提升。这是本项唯一需要改动现有脚本的地方。

镜号来源优先级：分镜 JSON 的 `shot_number` 优先，缺失时用 `_manifest.json` 的 `shot`。两者都没有时该镜进 `orphans` 并在 build 输出告警。

`query` 的输出直接给重出清单：

```text
@顾寒 出现于 2 个镜头、2 个视频段：
  第1集/组01 → 第1集/分镜/视频段/段01.mp4
  第1集/组05 → 第1集/分镜/视频段/段05.mp4
上游也需回流：第1集/成片/第1集.mp4（含上述段）
```

最后一行按 `references/studio-workflow.md` 的改稿回流表推导——有段要重出，成片必重剪。这条推导要写进代码而不是文档，否则用户还得自己查表。

### 3.4 与现有脚本的对接

`studio.py` 两处改动：

1. `status` 加 `--impact <资产名>` 参数，透传给 `impact_graph.py query`。
2. `impact_warnings` 保留 mtime 兜底，但当 `_impact.json` 存在且比相关文件新时，优先输出依赖图结论并标注来源为「依赖图」，避免两套提示打架。

`run_check` 加一项可选检查：`_impact.json` 存在时跑 `build --json` 并比对，若派生文件与实盘不符则告警（派生文件过期）。不进 `--strict` 的失败集。

### 3.5 验收用例

| 用例 | 前置 | 预期 |
|---|---|---|
| 单素材定位 | 分镜 JSON 两个镜头引用 @顾寒，manifest 两段对应 | `query @顾寒` 列出精确 2 镜 2 段，并推出成片需重剪 |
| 场景定位 | 分镜引用 S-01@day-crowd | `query S-01@day-crowd` 走 scenes 分支，结果与素材分支同构 |
| 断链入 orphans | 分镜引用不存在的 @刀疤 | build 完成不报错，`orphans` 含该名，退出码 0 但输出警告 |
| 派生文件过期 | build 后改分镜 JSON | `studio.py check` 告警「`_impact.json` 已过期」，不判失败 |
| 与 check_refs 同源 | 同一项目跑两脚本 | 断链清单完全一致（用断言比对两个集合） |

selftest 用临时项目造两镜两段，断言 `query` 输出的镜号集合与手写期望集合严格相等，不做「包含」断言。

### 3.6 风险与回滚

风险一：`_impact.json` 成为第二个事实源，与实盘漂移。缓解是把它定性为派生文件，`build` 幂等、可随时删，且 `check` 会检测过期。

风险二：从 `check_refs` 导入会带来脚本间耦合。缓解是只导入常量和纯函数，不导入 `main`，且导入失败时降级为内置默认正则（带注释说明这是兜底的重复定义）。

回滚：删 `scripts/impact_graph.py`、还原 `studio.py`、还原 `check_scene_plates.py` 的常量提升、删 `_impact.json`。

## 4 P0-3 内容质量评估与独立审查

### 4.1 缺口与证据

现有 22 个脚本的检查项全部是结构性的：字段齐不齐、字数超没超、引用断没断、接缝指标过没过。没有一项回答「这版剧本比上版好吗」。仓库无 `evaluations/` 目录，无盲评、无 holdout、无真实长篇回归夹具。

对标 zenstory-ai/drama-skills 的 `evaluations/`：16 题材合成案例，每个案例每 arm 固定 3 次 replicate、不做 best-of-N，Codex/Kimi 交换 A/B 位置盲评，共 96 份作品 + 192 份报告，门禁 fail-closed 要求 bundle sha256 一致。它的 `short-drama-review` 有 `REV-01`~`REV-15` 规则表 + 10 份分范围审查表，结论四档。

### 4.2 第一阶段：审查规则表（小）

新增 `references/review-rubric.md`，把审查从散文变成可勾选的表。分五个范围，每个范围一张表：

| 范围 | 规则数 | 每条形态 |
|---|---|---|
| 剧本 | 6 | 编号 RA-S-01、判据、不通过的具体样子、来源（人工/脚本） |
| 资产 | 5 | RA-A-01 起，同上 |
| 分镜 | 6 | RA-B-01 起，同上 |
| 提示词 | 5 | RA-P-01 起，同上 |
| 成片 | 5 | RA-F-01 起，同上 |

每条必须对应到已有脚本或明确的人工判定项，不留空话。示例三条：

- RA-S-03：每集有钩子与收尾，且不是标记词敷衍。判据：`check_script.py` 的 S5/S6 通过。不通过样子：写了「钩子：」但后面少于 6 字。
- RA-B-04：每镜标了转场代码与一句执行说明。判据：人工看分镜 JSON，`transition` 字段非空。不通过样子：转场全写「硬切」但下一镜构图不接。
- RA-F-02：接缝通过量化。判据：`qa_batch.py` 无超阈项。不通过样子：综合偏差排在首位的那条缝未处理就交付。

结论四档：`APPROVE` / `APPROVE_WITH_NOTES` / `REVISE` / `PROVISIONAL`。`PROVISIONAL` 专给「证据不足」——对应现有「未亲看不得声称通过」纪律。

新增 `scripts/review_check.py`（轻量）：吃一份 `_reviews/<集号>.md` 审查记录，校验格式——每条规则有结论、有证据行、`PROVISIONAL` 必须写缺什么证据。它不判断内容对错，只保证审查记录本身不是空壳。

### 4.3 第二阶段：评估门禁（大）

新增 `scripts/quality_gate.py`，形态如下：

```text
python scripts/quality_gate.py run <夹具目录> --arms a,b --replicates 3 [--out _eval/]
python scripts/quality_gate.py compare <_eval/run1> <_eval/run2>
python scripts/quality_gate.py selftest
```

夹具目录结构：

```text
夹具/
├── cases.json        16 个案例元数据：id / 题材 / 输入 / 期望维度
├── holdout.json      留出的 4 个案例，只在收口时跑一次
└── cases/            每案例一个目录，放输入与各 arm 产出
```

关键取舍三条：

1. **不做 best-of-N**，固定 replicate 次数。理由：best-of-N 会让结果随取样波动，无法比较 arm 优劣。
2. **盲评靠位置交换**，不靠隐藏身份。两个 arm 的产出每次跑随机左/右，评审只看到 A/B 两个位置。比「让评审不知道是谁做的」更可操作，因为评审本来就读得出文风。
3. **fail-closed**：案例 bundle 的 sha256 与 `cases.json` 记录不符时直接拒绝运行，不给「先跑完再说」。

评分维度八个，与调研报告一致：hook_payoff / causality / character / dialogue_action / visual_drama / pacing_retention / prompt_fidelity / genre_fit。每维 0-100，总分加权。权重写在 `cases.json` 里按题材可调——打脸题材 hook 权重要高，情感题材 character 权重要高。

### 4.4 与现有脚本的对接

`review_check.py` 不作为 `studio.py check` 的门禁项（审查是主观判断，不该阻断 CLI）。`quality_gate.py` 完全独立于工作室流程，是离线评估工具。

`studio.py status` 加一行软提示：若 `_reviews/` 存在但某集无审查记录，提示「本集尚无审查记录（跑 review-rubric 对应范围）」，不判失败。

### 4.5 验收用例

| 用例 | 前置 | 预期 |
|---|---|---|
| 规则表可落地 | 写完 review-rubric.md | 每条规则能指到具体脚本或写明人工判定，无「需综合判断」这类空话。人工核查 27 条 |
| 审查记录格式校验 | 造一份缺证据行的记录 | `review_check` 非零退出，指出哪条规则无证据 |
| PROVISIONAL 必填理由 | 造一份 PROVISIONAL 但未写缺什么 | 非零退出 |
| 夹具完整性 | 改一个案例文件但不更新 sha256 | `quality_gate run` 拒绝启动，退出码 2 |
| 重复性 | 同一夹具同一 arm 跑两次 | 两次的案例集合与评分维度完全一致，分数差异在预期抽样范围内 |
| holdout 隔离 | 正常运行 | holdout 案例不出现在 run 的产出里，只有 `--holdout` 显式开启才跑 |

selftest 用 3 个合成案例（非 16 个），只验流程与 fail-closed，不验评分质量——评分质量需要真实样本，属于第三批收口后的人工校准。

### 4.6 风险与回滚

最大风险是评估体系建完没人用。缓解：先只做第一阶段（规则表 + 记录格式校验），第二阶段等有真实多版本产出再启动。这也符合调研报告的判断——P0-3 第二步最贵且需要真实样本校准。

第二个风险是评分维度主观性导致结论不稳。缓解是在 `compare` 里输出「同 arm 两次跑的分数差」，差过大时明确标注「样本不足，结论不可用」，不给出假的确定性。

回滚：第一阶段删 `references/review-rubric.md` 与 `scripts/review_check.py`；第二阶段删 `scripts/quality_gate.py` 与 `_eval/`。两者独立。

## 5 P1-4 提示词血缘哈希

### 5.1 缺口与证据

`manifest.py:71-75` 每段只记 `script_version`（人手填的标签，如 `v21`）与 `scene_state`。`cmd_verify`（`manifest.py:113-145`）比对的是这两个字符串。

后果明确：改了提示词正文却忘了升版号，`verify` 给出「同源」的假绿。这是当前门禁里唯一一个可以被操作失误绕过的点。

### 5.2 数据契约

`_manifest.json` 的每条 shot 增加两个字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `prompt_sha256` | string | 提示词正文规范化后的 sha256 前 12 位 |
| `prompt_source` | string | 提示词来源的相对路径，如 `第1集/分镜/sb.json#组01` |

规范化规则要固定，否则同一份提示词会算出不同哈希：去首尾空白、内部连续空白压缩为单个空格、换行统一为 `\n`、不做大小写变换（中文无大小写，英文大小写有语义）。

### 5.3 实现

改 `scripts/manifest.py` 三处，不新建脚本：

1. `cmd_init` 与 `cmd_set` 增加 `--prompt`（提示词正文）与 `--prompt-source` 参数；给 `--prompt` 时算哈希写入。
2. `cmd_verify` 增加比对：同一批次内所有段 `prompt_sha256` 应一致；与 `--expect-prompt-sha` 比对（新增参数）。不一致计为 issue。
3. 新增 `--backfill-hash <分镜JSON>`：从分镜 JSON 抽每镜提示词回填哈希，解决存量项目。批量回填后要求重跑 `verify`。

向后兼容三条：

- shot 无 `prompt_sha256` 字段时，`verify` 只给 WARN「未记提示词哈希，无法验证内容同源」，不计入 issue、不改变退出码。
- 同一批次内部分有哈希、部分没有时，按「有哈希的互相比，无哈希的单列警告」处理。
- `--strict-hash` 参数可把「无哈希」升级为 issue，给已经全量回填的项目用。

### 5.4 与现有脚本的对接

`studio.py` 的 `run_check` 已串 `manifest verify`，无需改动。但 `print_check` 输出的摘要里要能看出哈希警告——因为 WARN 不改变退出码，用户在 `check` 绿的情况下仍需要看到「你没记哈希」这件事。

### 5.5 验收用例

| 用例 | 前置 | 预期 |
|---|---|---|
| 同名不同内容 | 版号相同，改提示词重算哈希 | `verify` 非零退出，报「同名不同内容」并列出哪几段哈希不一致 |
| 老清单兼容 | 手工造无哈希的清单 | `verify` 退出码 0，输出 WARN，不阻断 |
| strict 升级 | 老清单加 `--strict-hash` | 非零退出 |
| 规范化一致性 | 同一提示词带前后空白、多空格两种形态 | 两形态算出同一哈希（断言相等） |
| 回填 | 存量分镜 JSON 跑 `--backfill-hash` | 清单出现哈希，再跑 `verify` 通过 |

selftest 现有 5 段逻辑保留，新增上表五条。

### 5.6 风险与回滚

风险是哈希口径将来改动导致历史哈希全失效。缓解：把规范化函数单独命名 `normalize_prompt()` 并在 docstring 写明「改此函数等于改变哈希口径，需提供迁移脚本」。

回滚：`manifest.py` 单文件改动，还原即可；`_manifest.json` 里多出的字段是无害冗余，老代码忽略未知字段。

## 6 P1-5 对标测量器

### 6.1 缺口与证据

SKILL.md 的「对标参考流程」只有五维定性拆解（结构/节奏/钩子/字幕/素材穿插）+ 保留更换两栏清单。没有量化。SKILL.md 自身也承认：「节奏类维度注明『凭观感估计』，不虚构精确数值」。

对标 zenstory 的 `short-drama-breakdown`：七个子命令（measure / transcript / plan / profile / audio / shots / subtitles / subtitle-sheet），measure 用 ffprobe 测时长、切点、镜长与代表帧拼图，且**测法与自家成片同一把尺**。

### 6.2 数据契约

新增 `<项目>/_refs/<对标名>.json`，一个对标视频一份：

```json
{
  "name": "参考片A",
  "source": "D:/refs/a.mp4",
  "probed": "2026-11-12 20:00:00",
  "duration": 68.2,
  "frame_rate": "30/1",
  "resolution": "1080x1920",
  "cuts": [4.2, 7.8, 12.1],
  "shot_lengths": [4.2, 3.6, 4.3],
  "mean_shot_length": 3.1,
  "black_segments": [[0.0, 0.8], [67.4, 68.2]],
  "notes": "切点由场景检测得出，非人工标注"
}
```

`cuts` 的检测方式：复用 `check_seams.py` 已有的帧差计算思路，用 `ffprobe` + 逐帧灰度差找突变点。不引入 OpenCV。

### 6.3 实现

新建 `scripts/measure_ref.py`：

```text
python scripts/measure_ref.py probe <视频> [--out _refs/名字.json] [--threshold 0.35]
python scripts/measure_ref.py diff <参考JSON> <本项目成片目录> [--json]
python scripts/measure_ref.py selftest
```

`diff` 是本方案的核心价值：把参考片与本家片的同一组指标并排放，输出一张对照表：

| 指标 | 参考片 | 本项目 | 差 |
|---|---|---|---|
| 总时长 | 68.2s | 62.5s | -5.7s |
| 平均镜长 | 3.1s | 4.4s | +1.3s |
| 镜头数 | 22 | 14 | -8 |
| 黑场段数 | 2 | 0 | -2 |

对照表直接喂给 SKILL.md 的保留更换两栏清单——用户看到「平均镜长比参考片长 1.3 秒」，就知道节奏要加快。

诚实性约束写进代码：拿不到原片（只有截图或链接）时，`probe` 明确报「无法测量，缺原片」并退出，不做任何估算。这是 SKILL.md 既有纪律的工程化，不是新规矩。

### 6.4 与现有脚本的对接

`check_seams.py` 的帧差函数当前是内联的。方案要求提取为模块级 `frame_diff(a, b)` 供两处共用，行为不变。若提取成本高于复制 15 行，则允许复制并在注释写明「与 check_seams 同源，改一处须改两处」——这是本方案唯一允许的重复，因为跨脚本复用抽象比两处注释更贵。

`measure_ref.py` 不进 `studio.py check`，它是对标工具不是门禁。

### 6.5 验收用例

| 用例 | 前置 | 预期 |
|---|---|---|
| 自测片可测 | 用 ffmpeg 生成 3 段不同时长的测试片拼接 | `probe` 输出时长误差 <0.1s，切点数等于 2 |
| 无原片拒绝 | 只给一个 URL | 非零退出，输出「无法测量」 |
| 同一把尺 | 参考 JSON 与自家成片都跑 probe | 两者字段结构与数值口径完全一致（同一函数产出） |
| diff 对照 | 有参考 JSON 与成片 | 输出对照表，四个指标齐，差列带符号 |
| 无 ffmpeg 降级 | PATH 去掉 ffmpeg | 明确报「需要 ffmpeg」并退出 2，不静默成功 |

### 6.6 风险与回滚

风险：场景检测阈值在不同片子上表现差异大，切点数可能不准。缓解是把阈值做成参数并在输出里标注「切点由阈值 0.35 检测，可调」，提醒用户数值是工具的观测不是影片的事实。

回滚：删 `scripts/measure_ref.py` 与 `_refs/`。

## 7 P1-6 成本前置估算

### 7.1 缺口与证据

SKILL.md 的「批量/付费动作前与用户确认（估算 → 确认 → 记账）」三步，估算这一环要求「按镜数 × 单条积分算总量给用户」。`references/jimeng-seedance-2.5.md` 有积分数（5s 720P 约 130 分/条），但没有脚本把分镜 JSON 的镜数读出来算。

结果是每批要人工数镜、人工乘、人工加重试余量。这是纯机械劳动，且容易数错。

### 7.2 数据契约

不新增数据文件，只输出。可选写入 `_tasks.jsonl` 的 `est_credits` 字段（P0-1）。

### 7.3 实现

新建 `scripts/estimate_cost.py`：

```text
python scripts/estimate_cost.py <分镜JSON或项目> [--model seedance-2.5] [--duration 5] [--res 720p] [--retry 0.10] [--json]
```

三个关键函数：

| 函数 | 职责 |
|---|---|
| `load_unit_price(model, duration, res)` | 从内置单价表取单条积分；表来源标注为 `jimeng-seedance-2.5.md` 的实测值，未知组合报错不猜 |
| `count_shots(src)` | 分镜 JSON 数镜数；项目目录则递归数所有 `*.json` 并去重 |
| `compute(shots, unit, retry)` | 返回 `{shots, unit_price, subtotal, retry_buffer, total}` |

输出形如：

```text
估算：14 镜 × 130 分/条（5s 720p）= 1820 分
重试余量 10% = 182 分
建议额度 = 2002 分
口径：jimeng-seedance-2.5.md 实测（5s 720P 约 130 分/条），以生成时界面为准
```

最后一行必须带——单价是会变的，工具不能假装自己是权威。这是 SKILL.md「以上为编写时点的公开口径」的工程化。

### 7.4 与现有脚本的对接

`studio.py status` 加一行「预估剩余」：已花（P0-1 台账）与总估算（本脚本）相减。无台账时只显示总估算。

`estimate_cost.py` 的单价表与 `references/jimeng-seedance-2.5.md` 是双份数据。方案要求：单价表在脚本内以常量存在，但常量旁必须写 `# 来源：references/jimeng-seedance-2.5.md <节号>，实测日期 2026-10-10`，并在 selftest 里断言脚本常量与 md 里能解析到的数值一致——用一条断言防止两处漂移。

### 7.5 验收用例

| 用例 | 前置 | 预期 |
|---|---|---|
| 基本估算 | 14 镜分镜 JSON | 输出 14×130=1820，余量 182，总 2002 |
| 重试余量可配 | `--retry 0.2` | 余量按 20% 算 |
| 未知模型拒绝 | `--model 未知` | 非零退出，报「无单价数据」，不返回猜测值 |
| 单价不漂移 | 跑 selftest | 断言脚本常量等于 md 中解析值 |
| 目录汇总 | 传项目目录、多集各一份 JSON | 镜数合计正确，不重复计数（用文件名去重） |

### 7.6 风险与回滚

风险：平台调价后脚本给出过时估算。缓解是每条输出都带口径行，且 `--model` 未知即报错，让用户明确知道数值来自哪一版实测。

回滚：删 `scripts/estimate_cost.py`、还原 `studio.py` 一行改动。

## 8 P2-7 上游小说长文分析

### 8.1 缺口与证据

SKILL.md 第 17 行的「策划层指针」明确写：选题、市场情报、IP 定位、故事架构、节奏地图、剧本创作与多集规划用 `onlyshot-drama` 技能；本技能负责工作室化制作。

调研阶段我判断这是有意为之的边界、建议不做。**用户已明确要求纳入本方案**，故按用户决定设计，但职责切分必须写清，避免两个技能将来打架。

切分原则：`onlyshot-drama` 管「写什么」（选题、题材、爽点、拍法），本技能管「怎么把已有文本变成可排产的结构」（章节索引、情节点抽取、分集候选）。前者是创作判断，后者是结构化提取。新能力不产出任何剧情创意，只做清单与索引。

### 8.2 数据契约

新增 `<项目>/_novel/index.json`：

```json
{
  "source": "原著.txt",
  "chars": 52552,
  "encoding": "utf-8",
  "chapters": [
    {"no": 1, "title": "第一章 归乡", "start": 0, "end": 2400, "chars": 2400,
     "points": [{"id": "P001", "quote": "他推开那扇门", "offset": 120, "kind": "动作"}]}
  ],
  "unread": [],
  "read_range": "第1-20章（全）"
}
```

`points` 的 `quote` 与 `offset` 是核心——每个情节点都能回查原文位置，这是 Jellyfish 的 `EvidenceSpan` 思路。没有原文位置的情节点不可接受，因为下游无法核对。

### 8.3 实现

新建 `scripts/novel_index.py`：

```text
python scripts/novel_index.py index <原著txt> [--out _novel/index.json] [--chapters N]
python scripts/novel_index.py candidates <项目> [--episodes 24] [--json]
python scripts/novel_index.py selftest
```

职责严格限定：

1. `index` 只做机械工作——编码识别（复用 `check_script.py` 的 UTF-8/GBK 自动识别逻辑）、章节切分（正则匹配「第X章」等标题形态）、每章字数与起止偏移、情节点候选抽取（按段落与对话切分，不做语义判断）。
2. `candidates` 只做分集候选的**结构建议**——按情节点数量与字数给出「每集大致覆盖哪几章」的区间，不写剧情、不定钩子。
3. 不做的：不判断改编价值、不排题材爽点、不生成剧本。这些用 `onlyshot-drama`。

SKILL.md 的「策划层指针」段要改写为三段式：写什么用 onlyshot-drama、结构提取用本技能 novel_index、制作落地用本技能五工位。并在 `references/novel-adaptation.md` 里写清「读到哪、没读哪」的记录纪律——现有 SKILL.md 已要求「不凭梗概声称读过全剧」，这里把记录落成 `read_range` 字段。

长文分批读取的工程约束：文件超过 200KB 时 `index` 只出章节骨架并提示「正文过大，情节点抽取请分批 `--chapters 1-5`」，避免一次读入全部内容。这是现有「长剧本分批读时记录实际已读范围」纪律的工程化。

### 8.4 与现有脚本的对接

`studio.py init` 增加可选 `--novel <原著.txt>`，建项目时顺带跑索引，产物落 `_novel/`。不改变现有 `init` 的参数默认值，老用法不受影响。

`studio.py status` 在剧本台之前加一个软提示：有 `_novel/index.json` 但某章 `read_range` 未覆盖时，提示「原著第 N 章尚未分析」。

`novel_index.py` 不进 `check`——索引是准备材料，不是门禁。

### 8.5 验收用例

| 用例 | 前置 | 预期 |
|---|---|---|
| 章节切分 | 造 20 章、5 万字的合成 txt | 切出 20 章，总字数等于原文字数，各章 start/end 连续无重叠 |
| 编码识别 | GBK 与 UTF-8 两份同内容 | 两份都成功索引，`encoding` 字段标注正确，章节数与字数一致 |
| 情节点可回查 | 任取一个 point | 用 `start+offset` 定位原文，取出的字符串等于 `quote`（断言逐字相等） |
| 大文件分批 | 造 300KB 文件 | 只出骨架，提示分批，情节点为空 |
| 分集候选不越界 | 跑 `candidates` | 输出只有章节区间建议，无任何剧情描述（用关键词断言：不得含「钩子」「爽点」「反转」等创作词） |
| read_range 记录 | 只跑第 1-5 章 | `read_range` 记为「第1-5章」，`unread` 列出其余 |

### 8.6 风险与回滚

风险一：与 `onlyshot-drama` 职责重叠。缓解是代码层面禁止创作词——`candidates` 的输出用断言锁住，防止将来有人往里面加剧情建议。这条约束看起来严，但它是两个技能不打架的唯一保证。

风险二：章节标题形态太杂（「第1章」「第一章」「Chapter 1」「1.」）。缓解是正则表可扩展（常量列表），并在识别失败时明确报「未识别到章节结构」而不是硬切。

回滚：删 `scripts/novel_index.py`、`references/novel-adaptation.md`、`_novel/`，还原 `studio.py` 两处改动与 SKILL.md 的策划层指针段。

## 9 集成与文档同步

### 9.1 脚本清单同步面

新增七个脚本后，脚本总数从 22 变 29。以下五处必须同批更新（当前仓库的一致性要求，见 AGENTS.md 的「验证基线」）：

1. `.github/workflows/selftest.yml` 的脚本循环清单与标题里的数量。
2. `README.md` 的脚本数量表述。
3. `AGENTS.md` 的验证基线段落。
4. `docs/project-info.md` 的模块表（七个新行）。
5. `SKILL.md` 的「参考文件与脚本索引」表（七个新行）与更新记录。

数量表述的措辞统一为「N 个工程脚本」，避免中文数字与阿拉伯数字混用造成的漏改。

### 9.2 数据文件的关系图

```text
原著 → _novel/index.json ──┐
                            ├→ 剧本.md → 分镜 JSON → _manifest.json ─┐
studio.json ───────────────┘                    │                    │
                                                ├→ _tasks.jsonl ─────┤
                                                └→ _impact.json ─────┤
                                                                     └→ 成片 → _refs/*.json（对标）
```

三份派生文件（`_impact.json`、`_tasks.jsonl` 的折叠结果、`_refs/*.json`）都不入 git，写进 `.gitignore`。事实源只有用户写的 markdown 与 JSON。

### 9.3 新增 .gitignore 条目

```text
_impact.json
_tasks.jsonl
_novel/
_refs/
_eval/
_reviews/
```

其中 `_reviews/` 是否入库需用户决定——审查记录有留存价值，但可能含项目商业内容。方案默认入库（它是交付物的一部分），只在项目侧需要保密时排除。

### 9.4 SKILL.md 触发词同步

七个新能力对应新增触发话术，按现有触发示例表的格式追加：

| 话术 | 落点 |
|---|---|
| 「这批生成花了多少分，失败重抽浪费了多少」 | `task_ledger.py report` |
| 「改了顾寒的造型，哪些镜头和视频段要重出」 | `impact_graph.py query` |
| 「这一版剧本比上一版好吗」 | `review-rubric.md` + `quality_gate.py` |
| 「清单说同源，但我改过提示词，怎么确认」 | `manifest.py verify` 的哈希比对 |
| 「照这条爆款做一版，它的镜头节奏是多少」 | `measure_ref.py` |
| 「这 14 镜出片大概要多少积分」 | `estimate_cost.py` |
| 「这部长篇小说怎么切成 24 集」 | `novel_index.py candidates` |

description 字段需要补相应触发词，但当前 978 字符已接近 1024 上限。方案要求：新增触发词前先压缩旧词，总量控制在 1020 以内，并跑一次长度断言（现有 v2.5.0 已有此约束）。

## 10 验收总表与回滚

### 10.1 七项能力的收口判据

每项能力的收口统一为三条，缺一不算完成：

1. `python scripts/<新脚本>.py --selftest` 退出码 0。
2. CI 全量绿（29 项 selftest + demo 端到端回归）。
3. 至少一条真实项目数据跑通，记录在 `memory/agent-log.md` 的流水区。

### 10.2 批次回滚点

每批开工前建 git 提交作为回滚点。回滚粒度是「单个脚本 + 它的 studio.py 改动」，因为七项能力设计上互不依赖（除 P0-2 依赖 P0-1 的镜号约定，但该约定复用现有 `shot_number`，不构成硬依赖）。

### 10.3 待用户确认的四点

1. P0-3 是否只做第一阶段（规则表 + 记录格式校验）。第二阶段需要真实多版本产出才能校准，现在做了也可能白做。
2. P1-5 的切点检测是复用 `check_seams.py` 提取函数，还是允许复制 15 行并在两处注释同源。前者干净但改动既有脚本，后者改动小但有重复。我的倾向是后者，理由见 6.4。
3. `_reviews/` 是否入库。涉及项目商业内容留存，需要你定。
4. P2-7 的 `candidates` 只给章节区间建议，不给任何剧情或钩子——这个边界是否足够。如果希望它更主动（比如标出「这几章适合做一集」的候选边界），需要在职责切分上再明确一层。
