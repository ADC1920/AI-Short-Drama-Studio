# -*- coding: utf-8 -*-
"""分镜 JSON 迁移：补 scene_id 字段（C11 场景覆盖对账所需）。

背景：v3.1.0 起分镜契约新增 scene_id，用于回答「剧本写了 10 场，分镜是否每场都覆盖」。
老分镜 JSON 只有 shot_number + prompt_text，没有场景归属，缺这个字段就无法对账。

**为什么不能全自动**：分镜 JSON 里没有任何场景信息，从提示词正文反推场景属于猜测。
本脚本因此把「切分方案」显式化——要么你在命令行给，要么脚本给一个均分方案并标为待核对。

用法：
  # 1. 先看方案（默认干跑，不写盘）
  python scripts/migrate_storyboard.py <分镜.json> --script <剧本.md>

  # 2. 显式指定每场落在哪些镜号（推荐，无猜测）
  python scripts/migrate_storyboard.py <分镜.json> --script <剧本.md> \\
      --segments "S1:1-4,S2:5-7,S3:8-9" --apply

  # 3. 均分后逐镜手工核对（脚本会写明这是猜测）
  python scripts/migrate_storyboard.py <分镜.json> --script <剧本.md> --infer --apply

  # 4. 只验证现有 scene_id 是否完整（不写盘）
  python scripts/migrate_storyboard.py <分镜.json> --verify

  python scripts/migrate_storyboard.py --selftest

安全：--apply 前自动把原文件复制为 <原名>.bak-<时间戳>；干跑默认。
退出码：0 成功（或无需迁移）/ 1 方案有问题 / 2 用法或文件错误
"""
import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_SCENE_RE = re.compile(r"(?m)^#{1,4}\s*场景\s*(\d+)")
SEG_RE = re.compile(r"^\s*(S\d+)\s*:\s*(\d+)\s*(?:-\s*(\d+))?\s*$")


def read_script_scenes(path):
    """剧本 → ["S1","S2",...]。空列表表示剧本没有场次标题。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [f"S{n}" for n in SCRIPT_SCENE_RE.findall(text)]


def parse_segments(spec):
    """'S1:1-4,S2:5-7' → [("S1",1,4),("S2",5,7)]；格式错返回 None。"""
    out = []
    for part in spec.split(","):
        if not part.strip():
            continue
        m = SEG_RE.match(part)
        if not m:
            return None
        sid, lo = m.group(1), int(m.group(2))
        hi = int(m.group(3)) if m.group(3) else lo
        if hi < lo:
            return None
        out.append((sid, lo, hi))
    return out or None


def infer_segments(shot_numbers, scenes):
    """没有显式方案时按镜数均分场景——**这是猜测**，调用方必须在输出里标注。"""
    n = len(shot_numbers)
    k = len(scenes)
    if n == 0 or k == 0:
        return []
    out = []
    base, extra = divmod(n, k)
    cursor = 0
    for i, sid in enumerate(scenes):
        size = base + (1 if i < extra else 0)
        if size == 0:
            continue
        out.append((sid, cursor + 1, cursor + size))
        cursor += size
    return out


def build_plan(shots, segments):
    """[(sid,lo,hi)] + shots → {镜序: scene_id}。镜序按数组位置 1..N（与 shot_number 无关）。"""
    plan = {}
    for sid, lo, hi in segments:
        for i in range(lo, hi + 1):
            plan[i] = sid
    return plan


def validate_plan(shots, scenes, segments):
    """检查方案本身是否自洽：场次齐、覆盖满、无重叠、不越界。返回问题列表。"""
    problems = []
    n = len(shots)
    declared = [s[0] for s in segments]
    absent = [s for s in scenes if s not in declared]
    if absent:
        problems.append(f"方案漏掉场次：{'、'.join(absent)}")
    unknown = [s for s in declared if s not in scenes]
    if unknown:
        problems.append(f"方案中有剧本不存在的场次：{'、'.join(unknown)}")
    covered = set()
    for sid, lo, hi in segments:
        if lo < 1 or hi > n:
            problems.append(f"{sid} 的镜号范围 {lo}-{hi} 越界（共 {n} 镜）")
        for i in range(lo, hi + 1):
            if i in covered:
                problems.append(f"镜 {i} 被多个场次重复覆盖")
            covered.add(i)
    gap = [i for i in range(1, n + 1) if i not in covered]
    if gap:
        problems.append(f"以下镜号没有分配场景：{gap}")
    return problems


def apply_plan(sb_path, shots, plan, backup=True):
    """写回 scene_id。返回备份路径（未备份时为 None）。"""
    p = Path(sb_path)
    bak = None
    if backup:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = p.with_name(f"{p.name}.bak-{stamp}")
        shutil.copy2(p, bak)
    for i, shot in enumerate(shots, 1):
        if i in plan and isinstance(shot, dict):
            shot["scene_id"] = plan[i]
    data = _read_json(p)
    data["shots"] = shots
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return bak


def _read_json(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    return json.loads(text)


def verify(sb_path):
    """检查现有 scene_id 是否完整。返回 (缺失镜号列表, 出现过的场景集合)。"""
    data = _read_json(sb_path)
    shots = data.get("shots") or []
    missing, seen = [], set()
    for i, s in enumerate(shots, 1):
        sid = s.get("scene_id") if isinstance(s, dict) else None
        if isinstance(sid, str) and sid.strip():
            seen.add(sid.strip())
        else:
            missing.append(i)
    return missing, seen


def main():
    ap = argparse.ArgumentParser(description="分镜 JSON 补 scene_id（C11 覆盖对账前置）")
    ap.add_argument("storyboard", nargs="?", help="分镜 JSON 路径")
    ap.add_argument("--script", help="剧本 md 路径（读出场次清单）")
    ap.add_argument("--segments", help='显式切分方案，如 "S1:1-4,S2:5-7,S3:8-9"（镜序从 1 起）')
    ap.add_argument("--infer", action="store_true", help="无显式方案时按镜数均分（猜测，需人工核对）")
    ap.add_argument("--apply", action="store_true", help="写盘（默认干跑）")
    ap.add_argument("--no-backup", action="store_true", help="不备份原文件（不推荐）")
    ap.add_argument("--verify", action="store_true", help="只检查现有 scene_id 完整性")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.storyboard:
        ap.print_help()
        return 2
    sb = Path(args.storyboard)
    if not sb.is_file():
        print(f"分镜文件不存在：{sb}")
        return 2

    if args.verify:
        try:
            missing, seen = verify(sb)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"JSON 解析失败：{e}")
            return 2
        res = {"file": str(sb), "ok": not missing, "missing_shots": missing,
               "scenes_present": sorted(seen)}
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"分镜：{sb}")
            print(f"已声明场景：{'、'.join(sorted(seen)) if seen else '（无）'}")
            print(f"缺 scene_id 的镜：{len(missing)} 个" + (f"（{missing}）" if missing else ""))
            print("PASS（字段完整）" if not missing else "INCOMPLETE（需迁移）")
        return 0 if not missing else 1

    if not args.script:
        print("需要 --script 指定剧本（用于读场次清单）")
        return 2
    scenes = read_script_scenes(args.script)
    if not scenes:
        print(f"剧本里没找到「## 场景 N」标题：{args.script}")
        print("修法：确认剧本用「## 场景 N」格式写场次标题")
        return 2

    try:
        data = _read_json(sb)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"JSON 解析失败：{e}")
        return 2
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        print("分镜 JSON 没有 shots 数组或为空")
        return 2

    if args.segments:
        segments = parse_segments(args.segments)
        if segments is None:
            print(f'--segments 格式错：{args.segments!r}（应形如 "S1:1-4,S2:5-7"）')
            return 2
        source = "显式指定"
    elif args.infer:
        segments = infer_segments(shots, scenes)
        source = "按镜数均分（**猜测，须人工核对**）"
    else:
        print("需要 --segments（显式）或 --infer（均分猜测）之一，二者都没有时不做任何写盘。")
        print()
        print(f"剧本场次：{'、'.join(scenes)}")
        print(f"分镜镜数：{len(shots)}")
        print(f'示例：python {Path(sys.argv[0]).name} {sb} --script {args.script} '
              f'--segments "S1:1-{max(1, len(shots) // max(1, len(scenes)))}" --apply')
        return 2

    problems = validate_plan(shots, scenes, segments)
    plan = build_plan(shots, segments)

    print(f"分镜：{sb}")
    print(f"剧本：{args.script}（{'、'.join(scenes)}）")
    print(f"方案来源：{source}")
    print()
    print("切分：")
    for sid, lo, hi in segments:
        print(f"  {sid} ← 镜 {lo}-{hi}（{hi - lo + 1} 镜）")
    print()
    if problems:
        print("方案有问题：")
        for x in problems:
            print(f"  - {x}")
        print()
        print("未写盘。修好方案后重跑。")
        return 1

    print("方案自洽：场次齐、覆盖满、无重叠、不越界")
    if not args.apply:
        print()
        print("干跑结束（未写盘）。加 --apply 执行。")
        return 0

    bak = apply_plan(sb, shots, plan, backup=not args.no_backup)
    print(f"已写盘：{sb}")
    if bak:
        print(f"原文件已备份：{bak}")
    missing, seen = verify(sb)
    print(f"复核：缺 scene_id 的镜 {len(missing)} 个，已声明场景 {'、'.join(sorted(seen))}")
    return 0


def selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="migsb_"))
    try:
        script = tmp / "剧本.md"
        script.write_text("# 剧本\n\n## 场景 1｜甲\n\n内容\n\n## 场景 2｜乙\n\n内容\n",
                          encoding="utf-8")
        assert read_script_scenes(script) == ["S1", "S2"]

        sb = tmp / "sb.json"
        shots = [{"shot_number": str(i), "prompt_text": "无时间码，无字幕。"} for i in range(1, 7)]
        sb.write_text(json.dumps({"grid_layout": "2x3", "shots": shots}, ensure_ascii=False),
                      encoding="utf-8")

        # 解析方案
        assert parse_segments("S1:1-3,S2:4-6") == [("S1", 1, 3), ("S2", 4, 6)]
        assert parse_segments("S1:1") == [("S1", 1, 1)]
        assert parse_segments("garbage") is None
        assert parse_segments("S2:5-3") is None

        # 均分
        seg = infer_segments(shots, ["S1", "S2"])
        assert seg == [("S1", 1, 3), ("S2", 4, 6)], seg

        # 方案校验：漏场
        bad = [("S1", 1, 3)]
        assert any("漏掉场次" in p for p in validate_plan(shots, ["S1", "S2"], bad))
        # 方案校验：越界
        assert any("越界" in p for p in validate_plan(shots, ["S1"], [("S1", 1, 99)]))
        # 方案校验：重叠
        ov = [("S1", 1, 4), ("S2", 3, 6)]
        assert any("重复覆盖" in p for p in validate_plan(shots, ["S1", "S2"], ov))
        # 方案校验：空号
        gap = [("S1", 1, 2), ("S2", 5, 6)]
        assert any("没有分配场景" in p for p in validate_plan(shots, ["S1", "S2"], gap))
        # 合法方案无问题
        assert validate_plan(shots, ["S1", "S2"], [("S1", 1, 3), ("S2", 4, 6)]) == []

        # 干跑不写盘
        assert verify(sb)[0] == [1, 2, 3, 4, 5, 6]

        # 写盘 + 备份
        plan = build_plan(shots, [("S1", 1, 3), ("S2", 4, 6)])
        bak = apply_plan(sb, shots, plan, backup=True)
        assert bak and bak.is_file(), "应生成备份"
        missing, seen = verify(sb)
        assert missing == [], missing
        assert seen == {"S1", "S2"}, seen
        # 备份内容仍是老格式
        old = json.loads(bak.read_text(encoding="utf-8"))
        assert all("scene_id" not in s for s in old["shots"]), "备份应是迁移前的内容"

        print("selftest PASS（剧本场次解析 / 方案解析与拒绝非法 / 均分 / "
              "漏场·越界·重叠·空号四类方案问题 / 干跑不写盘 / 写盘含备份）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
