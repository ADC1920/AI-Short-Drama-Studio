# -*- coding: utf-8 -*-
"""成本前置估算（ai-short-drama-studio 技能）。

用途：把「估算 → 确认 → 记账」三步里的估算变成一条命令——读分镜 JSON 数镜数，
按内置单价表算总量，加重试余量，给出建议额度。替代人工数镜与手乘。

单价来源：references/jimeng-seedance-2.5.md 第三节（媒体实测，2026-07-31 发布期）。
单价会随平台调整，故每条输出都带口径行；未知模型/档位直接报错，不猜。

用法：
  python scripts/estimate_cost.py <分镜JSON或项目目录> [--model seedance-2.5] [--duration 5] [--res 720p] [--retry 0.10] [--json]
  python scripts/estimate_cost.py selftest

约定：
  - 只读分镜 JSON 的 shots 数组长度，不解析提示词内容；目录模式递归所有 *.json，
    排除 studio.json / _manifest.json / _impact.json 等非分镜文件。
  - 输出只算不存；要落账请用 task_ledger.py submit --est-credits。
  - 未知「模型 × 时长 × 分辨率」组合退出码 2，不给猜测值。
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REF_DOC = HERE.parent / "references" / "jimeng-seedance-2.5.md"
MD_SECTION = "## 三、会员与积分"

# 非分镜 JSON：项目配置、清单、派生索引
SKIP_NAMES = {"studio.json", "_manifest.json", "_impact.json"}
# 非分镜目录：派生索引与参考测量结果的产物目录
SKIP_DIRS = {"_novel", "_refs", "_eval", "_reviews", ".studio", ".tmp", "__pycache__"}

# 实测积分点（来源见 REF_DOC 第三节）。只收录实测过的档位，未实测的组合一律报错。
# 2.5 的 720P 实测为按秒线性：5s=130 / 10s=260 / 15s=390 / 30s=780。
UNIT_TABLE = {
    ("seedance-2.5", "720p"): {5: 130, 10: 260, 15: 390, 30: 780},
    ("seedance-2.0", "720p"): {5: 70},
}
CREDITS_PER_SECOND = {("seedance-2.5", "720p"): 26}  # 用于实测点之外的时长


def load_unit_price(model: str, duration: int, res: str):
    """取单条积分。实测点优先，其次尝试按秒外推（仅限有线性实测依据的档位）。"""
    key = (model, res.lower())
    table = UNIT_TABLE.get(key)
    if table is None:
        raise KeyError(f"无单价数据：模型 {model} × 分辨率 {res}。"
                       f"已收录档位：" + "、".join(f"{m}×{r}" for m, r in UNIT_TABLE))
    if duration in table:
        return table[duration]
    per_sec = CREDITS_PER_SECOND.get(key)
    if per_sec is None:
        raise KeyError(f"无单价数据：{model} × {duration}s × {res}。"
                       f"该档位只实测过 " + "、".join(f"{d}s" for d in table) + "，不外推")
    return per_sec * duration


def storyboard_files(src: Path):
    """分镜 JSON 清单：单文件直接返回；目录递归并排除非分镜文件与产物目录。"""
    if src.is_file():
        return [src]
    if not src.is_dir():
        return []
    out = []
    for p in sorted(src.rglob("*.json")):
        if any(part in SKIP_DIRS for part in p.relative_to(src).parts[:-1]):
            continue
        if p.name in SKIP_NAMES or p.name.startswith("_"):
            continue
        out.append(p)
    return out


def count_shots(src: Path):
    """(镜数, 明细[(文件, 镜数)])。读不出 shots 的文件跳过并在明细里标 0。"""
    files = storyboard_files(src)
    detail, total = [], 0
    for f in files:
        n = 0
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            shots = data.get("shots") if isinstance(data, dict) else None
            if isinstance(shots, list):
                n = len(shots)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            n = 0
        detail.append((str(f), n))
        total += n
    return total, detail


def compute(shots: int, unit_price: int, retry: float):
    subtotal = shots * unit_price
    buffer = int(round(subtotal * retry))
    return {"shots": shots, "unit_price": unit_price, "subtotal": subtotal,
            "retry_ratio": retry, "retry_buffer": buffer, "total": subtotal + buffer}


def print_report(res, model, duration, res_, detail=None):
    print(f"估算：{res['shots']} 镜 × {res['unit_price']} 分/条"
          f"（{duration}s {res_ or ''}{' ' if res_ else ''}{model}）= {res['subtotal']} 分")
    print(f"重试余量 {int(res['retry_ratio'] * 100)}% = {res['retry_buffer']} 分")
    print(f"建议额度 = {res['total']} 分")
    if detail:
        for path, n in detail:
            print(f"  {n:>3} 镜  {path}")
    print(f"口径：{REF_DOC.name} 第三节媒体实测（2026-07-31 发布期，量级参考），"
          f"以生成时界面为准")


def cmd_estimate(args):
    src = Path(args.src)
    if not src.exists():
        print(f"路径不存在：{src}")
        return 2
    shots, detail = count_shots(src)
    if shots == 0:
        print(f"未找到任何分镜 shots：{src}（目录模式会递归 *.json 并取 shots 数组）")
        return 2
    try:
        unit = load_unit_price(args.model, args.duration, args.res)
    except KeyError as e:
        print(str(e.args[0]))
        return 2
    res = compute(shots, unit, args.retry)
    if args.json:
        res.update({"model": args.model, "duration": args.duration,
                    "res": args.res, "files": [{"path": p, "shots": n} for p, n in detail]})
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print_report(res, args.model, args.duration, args.res,
                     detail if len(detail) > 1 else None)
    return 0


def parse_doc_points():
    """从参考文档解析实测积分点，用于断言脚本常量未漂移。"""
    text = REF_DOC.read_text(encoding="utf-8")
    start = text.find(MD_SECTION)
    if start < 0:
        return {}
    seg = text[start:text.find("\n## ", start + 1) if text.find("\n## ", start + 1) > 0 else len(text)]
    line = next((l for l in seg.splitlines() if "积分消耗" in l), "")
    if not line:
        return {}
    import re
    points = {}
    m = re.search(r"(\d+)\s*秒\s*720P\s*约\s*(\d+)\s*积分", line)
    if m:
        points[int(m.group(1))] = int(m.group(2))
    for d, c in re.findall(r"(\d+)\s*秒\s*(?!720P)(\d+)(?!\s*积分)", line):
        if int(d) not in points:
            points[int(d)] = int(c)
    return points


def selftest():
    import shutil
    import tempfile
    ok = True

    # 1 基本估算：14 镜 × 130 = 1820，余量 182，总 2002
    r = compute(14, 130, 0.10)
    assert r["subtotal"] == 1820 and r["retry_buffer"] == 182 and r["total"] == 2002, r

    # 2 重试余量可配
    r = compute(10, 130, 0.20)
    assert r["retry_buffer"] == 260 and r["total"] == 1560, r

    # 3 实测点命中
    assert load_unit_price("seedance-2.5", 5, "720p") == 130
    assert load_unit_price("seedance-2.5", 10, "720p") == 260

    # 4 实测点外按秒外推（2.5 720P 有线性实测依据）
    assert load_unit_price("seedance-2.5", 8, "720p") == 26 * 8
    assert load_unit_price("seedance-2.5", 30, "720p") == 780, "30s 应取实测点而非外推"

    # 5 未知模型必须报错而非猜
    for bad in [("seedance-9", 5, "720p"), ("seedance-2.5", 5, "4k"), ("seedance-2.0", 10, "720p")]:
        try:
            load_unit_price(*bad)
            raise AssertionError(f"未知组合应报错：{bad}")
        except KeyError:
            pass

    # 6 脚本常量与参考文档实测值一致（防两处漂移）
    doc = parse_doc_points()
    assert doc, f"未能从 {REF_DOC} 解析实测积分点"
    for d, c in doc.items():
        assert UNIT_TABLE[("seedance-2.5", "720p")].get(d) == c, \
            f"{d}s 脚本 {UNIT_TABLE[('seedance-2.5', '720p')].get(d)} 与文档 {c} 不一致"

    # 7 目录模式：多文件合计、非分镜 JSON 被排除
    tmp = Path(tempfile.mkdtemp(prefix="ec_st_"))
    try:
        (tmp / "第1集" / "分镜").mkdir(parents=True)
        for name, n in [("sb.json", 9), ("sb2.json", 5)]:
            (tmp / "第1集" / "分镜" / name).write_text(
                json.dumps({"shots": [{"shot_number": str(i)} for i in range(n)]}),
                encoding="utf-8")
        (tmp / "第1集" / "分镜" / "_manifest.json").write_text(
            json.dumps({"shots": [{"shot": f"x{i}"} for i in range(100)]}), encoding="utf-8")
        (tmp / "studio.json").write_text(json.dumps({"title": "x"}), encoding="utf-8")
        # 派生目录里的 JSON 不应被当分镜（_novel/index.json 曾污染明细）
        (tmp / "_novel").mkdir()
        (tmp / "_novel" / "index.json").write_text(
            json.dumps({"chapters": [{"no": i} for i in range(30)]}), encoding="utf-8")
        shots, detail = count_shots(tmp)
        assert shots == 14, f"目录合计应为 14，实际 {shots}（{detail}）"
        assert len(detail) == 2, f"应只计 2 个分镜文件，实际 {len(detail)}"
        assert all("_novel" not in p for p, _ in detail), detail
        # 单文件模式
        s1, _ = count_shots(tmp / "第1集" / "分镜" / "sb.json")
        assert s1 == 9
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("selftest PASS（7 项：基本估算/余量可配/实测点/按秒外推/未知拒绝/常量不漂移/目录合计）")


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
        return
    ap = argparse.ArgumentParser(description="成本前置估算")
    ap.add_argument("src", help="分镜 JSON 或项目目录")
    ap.add_argument("--model", default="seedance-2.5")
    ap.add_argument("--duration", type=int, default=5, help="单条时长秒（实测点 5/10/15/30）")
    ap.add_argument("--res", default="720p")
    ap.add_argument("--retry", type=float, default=0.10, help="重试余量比例，默认 0.10")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sys.exit(cmd_estimate(args))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
