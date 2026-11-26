# -*- coding: utf-8 -*-
"""契约检查：退出码语义 + --json 可解析性。把 references/cli-contract.md 的约定变成机检。

两条不变量：
  I1 无参调用必须 exit 2（不是 0）——否则 agent 会把「没检查」当「检查通过」
  I2 exit 0/1 时 --json 输出必须能被 json.loads 解析；exit 2 是用法错，不要求 JSON

用法：
  python scripts/check_contract.py                      # 对真实仓库跑
  python scripts/check_contract.py --json
  python scripts/check_contract.py --selftest

退出码：0 全部满足 / 1 有违例 / 2 用法或文件错误
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

# I1：这些脚本无参时必须 exit 2
NOARG_MUST_BE_2 = [
    "check_scene_plates", "gen_scene_sheet", "validate_storyboard", "check_refs",
    "check_script", "lint_prompt", "estimate_cost", "check_seams", "qa_batch",
    "short_plan", "studio",
]

DEMO = "examples/demo-multi-ep"

# I2：这些调用在 exit 0/1 时必须输出可解析 JSON
JSON_CALLS = [
    ("studio status", ["studio.py", "status", DEMO, "--json"]),
    ("studio check", ["studio.py", "check", DEMO, "--json"]),
    ("validate_storyboard",
     ["validate_storyboard.py", f"{DEMO}/第1集/分镜/sb.json", "--json", "--no-log"]),
    ("check_refs", ["check_refs.py", DEMO, "--json"]),
    ("check_script", ["check_script.py", DEMO, "--json"]),
    ("estimate_cost", ["estimate_cost.py", DEMO, "--json"]),
    ("task_ledger", ["task_ledger.py", "report", DEMO, "--json"]),
    ("impact_graph", ["impact_graph.py", "query", DEMO, "--asset", "@顾寒", "--json"]),
]


def run(cmd, cwd):
    try:
        cp = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=180)
        return cp.returncode, cp.stdout or "", cp.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)


def check_repo(root):
    out = []

    def add(level, rule, msg, fix=""):
        out.append({"level": level, "rule": rule, "msg": msg, "fix": fix})

    # I1 无参退出码
    for name in NOARG_MUST_BE_2:
        p = root / "scripts" / f"{name}.py"
        if not p.is_file():
            add("FAIL", "I1", f"{name}.py 不存在", "确认脚本清单与 check_contract.py 同步")
            continue
        rc, _, _ = run([sys.executable, str(p)], root)
        if rc != 2:
            add("FAIL", "I1", f"{name}.py 无参 exit={rc}（应为 2）",
                "无参路径改成 return 2，且入口用 sys.exit(main()) 取返回值")

    # I2 JSON 可解析
    for label, parts in JSON_CALLS:
        script = root / "scripts" / parts[0]
        if not script.is_file():
            add("FAIL", "I2", f"{label}: {parts[0]} 不存在", "同步脚本清单")
            continue
        rc, stdout, _ = run([sys.executable, str(script)] + parts[1:], root)
        if rc == 2:
            continue  # 用法错，契约不要求 JSON
        try:
            json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            add("FAIL", "I2", f"{label}: exit={rc} 但输出不可解析为 JSON",
                "给该脚本的 --json 分支补结构化输出，或把早期 return 包进 JSON")

    return out


def summarize(findings):
    fails = [x for x in findings if x["level"] == "FAIL"]
    return {"total": len(findings), "fail": len(fails),
            "warn": len(findings) - len(fails)}


def main():
    ap = argparse.ArgumentParser(description="契约检查：退出码 + JSON 可解析性")
    ap.add_argument("root", nargs="?", help="技能目录（默认脚本上级）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if not (root / "scripts").is_dir():
        print(f"不是技能目录（缺 scripts/）：{root}")
        return 2

    findings = check_repo(root)
    res = {"root": str(root), "ok": not findings, "findings": findings,
           "summary": summarize(findings)}
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"契约检查：{root}")
        print(f"  I1 无参必须 exit 2：{len(NOARG_MUST_BE_2)} 个脚本")
        print(f"  I2 JSON 可解析（exit 0/1）：{len(JSON_CALLS)} 处调用")
        print()
        for f in findings:
            print(f"[{f['level']}] {f['rule']} {f['msg']}")
            if f["fix"]:
                print(f"        修法：{f['fix']}")
        s = res["summary"]
        print(f"\n结果：{'PASS' if res['ok'] else 'FAIL'}（{s['fail']} FAIL）")
    return 0 if res["ok"] else 1


def selftest():
    import tempfile
    import shutil
    tmp = Path(tempfile.mkdtemp(prefix="contract_"))
    try:
        scripts = tmp / "scripts"
        scripts.mkdir()
        # 合规脚本：无参 exit 2，带 --json 输出可解析
        (scripts / "good.py").write_text(
            'import argparse, json, sys\n'
            'ap = argparse.ArgumentParser()\n'
            'ap.add_argument("x", nargs="?")\n'
            'ap.add_argument("--json", action="store_true")\n'
            'a = ap.parse_args()\n'
            'if not a.x:\n'
            '    ap.print_help(); sys.exit(2)\n'
            'print(json.dumps({"ok": True}))\n', encoding="utf-8")
        # 假绿脚本：无参 exit 0
        (scripts / "fakegreen.py").write_text(
            'import sys\nsys.exit(0)\n', encoding="utf-8")

        # 直接调 check_repo 的 I1 部分（用临时清单）
        old1, old2 = NOARG_MUST_BE_2[:], JSON_CALLS[:]
        try:
            NOARG_MUST_BE_2[:] = ["good", "fakegreen"]
            JSON_CALLS[:] = []
            fs = check_repo(tmp)
            assert any(x["rule"] == "I1" and "fakegreen" in x["msg"] for x in fs), fs
            assert not any("good" in x["msg"] for x in fs), fs
        finally:
            NOARG_MUST_BE_2[:] = old1
            JSON_CALLS[:] = old2

        print("selftest PASS（I1 检出假绿且不误报合规脚本）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
