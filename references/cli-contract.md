# CLI 契约（agent 调用面）

> 本文件是脚本输出与退出码的单一权威源。agent 调本技能的脚本前读这一页，不必逐个 `--help` 试探。
> 变更纪律：新增脚本或改退出码必须同步本文件，`scripts/check_skill.py` 会核对索引完整性。

## 目录

- [一、退出码契约](#一退出码契约)
- [二、两种输出格式](#二两种输出格式)
- [三、JSON 输出结构](#三json-输出结构)
- [四、脚本分类：谁有 --json](#四脚本分类谁有---json)
- [五、错误消息规范](#五错误消息规范)
- [六、已知的语义特殊性](#六已知的语义特殊性)
- [七、agent 调用推荐姿势](#七agent-调用推荐姿势)

## 一、退出码契约

所有脚本共用一张表。判读退出码**先看表再决定动作**，不要只判 `== 0`。

| 码 | 含义 | agent 该做什么 |
|---|---|---|
| `0` | 通过 / 成功 / 无异常 | 继续下一步 |
| `1` | 检查不通过（有 findings 需要修） | 读输出定位问题，改产物，重跑 |
| `2` | 用法错误 / 路径不存在 / 缺依赖 / 未执行 | **不要重试**。检查参数与路径，或补依赖 |
| `3` | 前置条件不满足（拒绝执行） | **不要原样重试**。需先改状态或加显式 flag |
| `4` | 环境或输入损坏（工具无法完成） | 需人工介入。换输入或修环境 |

判读要点：

- **`2` 不是「检查失败」**，是「这次根本没检查成」。把它当 `1` 处理会导致 agent 反复改一个没问题的产物。
- **`3` 一定不能盲目重试**。三处 `3` 各有不同前置条件，见[第六节](#六已知的语义特殊性)。
- **无参数调用返回 `2`** 是正确行为。若某脚本无参返回 `0`，那是缺陷（历史上 `check_scene_plates.py` 与 `gen_scene_sheet.py` 曾如此，v3.1.0 已修并加 selftest 守卫）。

## 二、两种输出格式

每个会返回数据的脚本都支持两种形态（官方 MCP 最佳实践要求）：

- **人类可读（默认）**：中文散文与表格，给自己看、给用户看。
- **机器可读（`--json`）**：结构化字段，给 agent 解析。

`--json` 只影响 stdout 的形态，不影响退出码，也不改变检查逻辑。

**一条必须记住的例外**：`--json` 保证「**真的执行了检查**时输出可解析」，**不保证用法错误时输出 JSON**。参数缺失、路径不存在这类 `exit 2` 场景下，脚本通常直接打印 argparse 的 usage 或一行中文提示。

所以 agent 的正确读法是：**先判退出码，再决定要不要解析 JSON**。

```python
if rc == 2:
    read_stderr_text()        # 用法错，别试图解析 JSON
elif rc in (0, 1):
    data = json.loads(stdout) # 检查真跑过，JSON 必定可解析
```

为什么不做成「错误也输出 JSON」：那要在每个脚本的每条早退路径上加分支，代码量与重复度都高，而 `exit 2` 本身已经足够 agent 精确分支。契约用一条规则覆盖，比给 11 个脚本各加十处 JSON 打印更省。

## 三、JSON 输出结构

### 门禁类脚本（检查产物是否合格）

统一形态：

```json
{
  "ok": true,
  "findings": [
    {
      "level": "FAIL",
      "rule": "S2",
      "file": "第1集/剧本.md",
      "line": 12,
      "msg": "集号与目录不一致：目录第1集，正文写第2集",
      "fix": "把正文集号改成第1集，或把文件移到第2集目录"
    }
  ],
  "summary": {"total": 1, "fail": 1, "warn": 0}
}
```

字段含义：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | bool | 等价于退出码 0（`summary.fail == 0`） |
| `findings[].level` | `"FAIL"` / `"WARN"` | FAIL 阻断，WARN 不阻断 |
| `findings[].rule` | str | 规则编号（如 `S2`、`C11`、`K7`），用于定位与统计 |
| `findings[].file` | str | 相对项目根的文件路径；无文件粒度时为空串 |
| `findings[].line` | int | 行号；无行粒度时为 `0` |
| `findings[].msg` | str | 问题描述（中文，说清是什么错） |
| `findings[].fix` | str | **修法**（官方要求 actionable error messages；能给出就给出） |
| `summary` | obj | `total` / `fail` / `warn` 三个计数 |

### 聚合类脚本（一次跑多个门禁）

`studio.py check --json` 在门禁结构外面再加一层：

```json
{
  "project": "<绝对路径>",
  "ok": false,
  "results": [
    {
      "name": "check_refs 素材与 @引用",
      "ok": false,
      "exit": 1,
      "findings": [
        {"level": "FAIL", "rule": "R1", "file": "第1集/剧本.md", "line": 0,
         "msg": "引用了不存在的素材：@顾寒", "fix": "把 03_assets/顾寒.png 补上，或改提示词里的名字"}
      ],
      "output": "<子脚本原始输出，作为兜底保留>"
    }
  ],
  "summary": {"total": 3, "passed": 2, "failed": 1}
}
```

`output` 字段是为了向后兼容与调试保留的原始文本；**agent 应优先读 `findings[]`**，因为 `output` 是截断的。

### 查询类脚本（返回数据而非检查结果）

`studio.py status` / `impact_graph.py query` / `task_ledger.py report` / `estimate_cost.py` 等返回业务数据，结构各自定义但都满足：

- 顶层是对象（不是数组）；
- 所有键为英文短名；
- 不出现 `Path` 等不可序列化对象（`--json` 必定可被 `json.loads` 解析）；
- 时间字段用 `YYYY-MM-DD HH:mm:ss` 格式字符串。

## 四、脚本分类：谁有 --json

### 门禁类（检查产物）

| 脚本 | `--json` | 主要 rule 前缀 | 用途 |
|---|---|---|---|
| `check_script.py` | 有 | `S*` | 剧本结构、占位、钩子、台词预算 |
| `validate_storyboard.py` | 有 | `C*` | 分镜 JSON 结构、词层、覆盖对账（C11） |
| `check_refs.py` | 有 | `R*` | @引用 vs 素材文件名断链 |
| `lint_prompt.py` | 有 | `L*` | 提示词空词、运镜歧义 |
| `check_scene_plates.py` | 有 | — | 场景板字段与跨文件引用 |
| `review_check.py` | 有 | — | 审查记录格式是否空壳 |
| `manifest.py verify` | 有 | — | 相邻段同源核对 + 提示词哈希 |
| `check_seams.py` | 有 | — | 接缝 SSIM 量化 |
| `qa_batch.py` | 有 | — | 接缝 + 同源一次性验收 |
| `check_skill.py` | 有 | `K*` | 技能本体规范体检 |
| `short_plan.py` | 有 | — | 短视频口播时长预算 |

### 聚合类

| 脚本 | `--json` | 说明 |
|---|---|---|
| `studio.py status` | 有 | 十段进度、焦点段、成本、影响面 |
| `studio.py check` | 有 | 一次跑 7 类门禁，输出 `results[]` |

### 查询 / 生成类

| 脚本 | `--json` | 说明 |
|---|---|---|
| `impact_graph.py query` | 有 | 改稿影响面（素材 → 镜 → 段） |
| `task_ledger.py report/recover` | 有 | 成本汇总 / 未回执清单 |
| `estimate_cost.py` | 有 | 出片积分估算 |
| `measure_ref.py probe/diff` | 有 | 参考片与成片同一把尺测量 |
| `novel_index.py index/candidates` | 有 | 原著结构索引 / 分集建议 |

### 无 `--json`（纯人类可读或纯写盘）

`init_project.py` / `make_grid.py` / `concat_clips.py` / `trim_clips.py` / `gen_script.py` / `archive_old_docx.py` / `fix_table_pagination.py` / `style_code_blocks.py` / `sync_entity.py` / `check_double_root.py` / `tts_voice.py` / `gen_scene_sheet.py`。

这些是「做一件事」而非「查一件事」的脚本，agent 只需判退出码，不需要解析输出。需要机读进度时读它们落盘的产物文件。

## 五、错误消息规范

参考官方工具设计指南，错误消息要能被 agent 直接用来决定下一步：

- **说清是什么错**，不要只报「失败」；
- **给出修法**（JSON 的 `fix` 字段，人类可读输出的「修法：」行）；
- **能列出候选就列**：路径不存在时尽量列出同目录下的真实候选；
- **不要暴露 traceback 作为唯一信息**：未被捕获的异常应转成人话。

## 六、已知的语义特殊性

### 退出码 `3` 的三处不同含义

| 位置 | 语义 | 正确动作 |
|---|---|---|
| `task_ledger.py submit` | 该镜已有运行中任务，拒绝重复提交 | **不要重试**（会重复计费）。先 `result` 或 `cancel`，确需重提加 `--force` |
| `novel_index.py candidates` | 内部断言失败（输出混入创作词） | 属内部错误，上报不重试 |
| `concat_clips.py` | 待拼接段的参数与基准不一致，拒绝拼接 | **不要重试**。先统一生成参数重出该段，或加 `--reencode-mismatch` |

**共同点**：`3` 永不表示「临时故障，等等再试」。按可重试处理 `task_ledger` 那处会造成重复扣费。

### 退出码 `4`（仅 `concat_clips.py`）

重编码失败 / 拼接失败 / 成片不可读。属环境或输入问题，需人工介入。

### argparse 子命令型脚本无参返回 `0`

`impact_graph` / `novel_index` / `task_ledger` / `measure_ref` / `manifest` 是子命令结构，无参时 argparse 打印 usage 并 exit 0。**agent 调用这些脚本必须显式给子命令**，不要把「exit 0」当成功。

## 七、agent 调用推荐姿势

```bash
# 1. 想知道项目做到哪了
python scripts/studio.py status <项目> --json

# 2. 想一次跑完所有门禁并拿到结构化结果
python scripts/studio.py check <项目> --json
# -> 读 results[].findings[]，不要读 output

# 3. 只跑单个门禁
python scripts/validate_storyboard.py <分镜.json> --json
python scripts/check_script.py <剧本.md> --json
python scripts/check_refs.py <项目> --json

# 4. 改稿影响面
python scripts/impact_graph.py build <项目>
python scripts/impact_graph.py query <项目> --asset @角色名 --json

# 5. 技能本体是否规范（改完 SKILL.md / references 后必跑）
python scripts/check_skill.py --json
```

退出码判读模板：

```python
if rc == 0:
    proceed()
elif rc == 1:
    fix_from(findings)      # 有具体问题，改产物
elif rc == 2:
    check_args_or_paths()   # 调用姿势错，别改产物
elif rc == 3:
    resolve_precondition()  # 前置条件，别原样重试
else:
    escalate()              # 4 或其他，需人看
```
