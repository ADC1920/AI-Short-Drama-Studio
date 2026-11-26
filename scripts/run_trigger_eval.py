# -*- coding: utf-8 -*-
"""触发评测（trigger eval）：检验 skill description 与触发话术表是否自洽。

两档设计——离线档现在就能跑，真评测档需要模型通道：

  档 A（离线，默认）：静态一致性检查，不需要任何 API
    - 每条触发话术都写了落点（不能只列话术不写去哪）
    - 落点引用的文件/脚本真实存在（无死链）
    - description 覆盖触发话术里的高频关键词（漏掉的词意味着该说法触发不到）
    - 话术无重复

  档 B（真评测，--live）：需要模型通道，逐条问「这句话你会用这个技能吗」
    本机没有 claude 命令也无 API key 时明确报「无法执行」并 exit 2，
    绝不静默跳过冒充通过。

为什么分两档：官方 skill-creator 的 run_eval.py 靠 claude -p 做真评测。
本技能的开发环境不一定有该通道；但「话术表与落点自洽」「描述覆盖关键词」
这类静态问题不需要模型也能查出来，且这两类正是描述漂移的主要来源。

用法：
  python scripts/run_trigger_eval.py                    # 离线档
  python scripts/run_trigger_eval.py --json
  python scripts/run_trigger_eval.py --live             # 真评测（需 claude CLI）
  python scripts/run_trigger_eval.py --selftest

数据源：SKILL.md 的「触发示例」表 + front-matter description。
退出码：0 通过 / 1 有 FAIL / 2 无法执行（缺通道或缺文件）
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

TRIGGER_SECTION = "## 触发示例"
# 触发话术里的高频业务词——这些词若不在 description 里，用户那样说就触发不到
KEY_TERMS = [
    "短剧", "漫剧", "动态漫", "竖屏", "短视频", "口播", "钩子", "分镜", "提示词",
    "配音", "转场", "调色", "完播率", "Seedance", "素材", "角色", "场景板",
]


def parse_skill(skill_md):
    """→ (description 文本, [(话术, 落点)] 触发表)"""
    text = Path(skill_md).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^description:\s*(.+?)$", text, re.M)
    desc = ""
    if m:
        desc = m.group(1).strip()
        if len(desc) >= 2 and desc[0] == desc[-1] and desc[0] in "\"'":
            desc = desc[1:-1]

    rows = []
    if TRIGGER_SECTION in text:
        seg = text[text.index(TRIGGER_SECTION):]
        # 截到下个 ## 标题
        nxt = re.search(r"\n##\s+", seg[3:])
        if nxt:
            seg = seg[:nxt.start() + 3]
        for ln in seg.splitlines():
            if not ln.startswith("|"):
                continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            say, landing = cells[0], cells[1]
            if say in ("用户话术示例",) or set(say) <= set("-: "):
                continue
            # 去掉话术外层「」
            say_clean = say.strip("「」")
            if say_clean:
                rows.append((say_clean, landing))
    return desc, rows


def check_offline(root, desc, rows):
    """静态一致性检查，返回 findings。"""
    out = []

    def add(level, rule, msg, fix=""):
        out.append({"level": level, "rule": rule, "file": "SKILL.md", "line": 0,
                    "msg": msg, "fix": fix})

    if not rows:
        add("FAIL", "E1", "没解析到触发示例表（## 触发示例 下无表格行）",
            "确认该节存在且是 | 话术 | 落点 | 两列表格")
        return out

    # E2 落点不能空
    for say, landing in rows:
        if not landing.strip() or landing.strip() in ("-", "—"):
            add("FAIL", "E2", f"话术没有落点：「{say}」", "写清这句话该进哪一段/哪个脚本")

    # E3 落点里引用的文件必须存在
    refs = set()
    for _, landing in rows:
        refs.update(re.findall(r"`?(references/[a-z0-9-]+\.md)`?", landing))
        refs.update(re.findall(r"`?(scripts/[a-z0-9_]+\.py)`?", landing))
    for r in sorted(refs):
        if not (Path(root) / r).is_file():
            add("FAIL", "E3", f"落点引用了不存在的文件：{r}", "改成真实路径，或补该文件")

    # E4 话术重复
    seen = {}
    for say, _ in rows:
        if say in seen:
            add("WARN", "E4", f"话术重复：「{say}」", "删掉重复行，触发面靠关键词覆盖而非堆行数")
        seen[say] = True

    # E5 description 关键词覆盖
    if desc:
        missing = [t for t in KEY_TERMS if t not in desc]
        # 触发话术里实际出现过的词才算「应该覆盖」
        used = [t for t in missing if any(t in say for say, _ in rows)]
        if used:
            add("WARN", "E5",
                f"触发话术用到但 description 未含的词：{'、'.join(used)}",
                "把这些词补进 description，否则用户这样问时技能不会被触发")
    else:
        add("FAIL", "E5", "front-matter 没有 description", "补 description（做什么 + 何时用）")

    return out


def run_live(desc, rows, limit=None):
    """真评测：逐条问模型。缺通道时抛 RuntimeError，由调用方转 exit 2。"""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError(
            "真评测需要 claude CLI 或等价模型通道，本机未找到。"
            "离线档（不加 --live）可查静态一致性。")
    import subprocess
    mis = []
    for say, _ in (rows[:limit] if limit else rows):
        prompt = (f"技能描述如下：\n{desc}\n\n用户说：「{say}」。"
                  f"你会调用这个技能吗？只回答 YES 或 NO。")
        try:
            cp = subprocess.run([exe, "-p", prompt], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(f"调用模型失败：{e}") from e
        ans = (cp.stdout or "").strip().upper()
        if not ans.startswith("YES"):
            mis.append({"say": say, "answer": ans[:80]})
    return mis


def summarize(findings):
    fails = [x for x in findings if x["level"] == "FAIL"]
    return {"total": len(findings), "fail": len(fails),
            "warn": len(findings) - len(fails)}


def main():
    ap = argparse.ArgumentParser(description="触发评测：description 与话术表自洽性")
    ap.add_argument("root", nargs="?", help="技能目录（默认取脚本上级）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--live", action="store_true", help="真评测（需 claude CLI）")
    ap.add_argument("--limit", type=int, default=0, help="--live 时只测前 N 条")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        print(f"SKILL.md 不存在：{skill_md}")
        return 2

    desc, rows = parse_skill(skill_md)
    findings = check_offline(root, desc, rows)

    live_err = None
    live_mis = []
    if args.live:
        try:
            live_mis = run_live(desc, rows, args.limit or None)
        except RuntimeError as e:
            live_err = str(e)

    res = {"root": str(root), "offline_findings": findings,
           "summary": summarize(findings), "rows": len(rows),
           "live": ({"ran": False, "error": live_err} if live_err
                    else ({"ran": True, "missed": live_mis} if args.live
                          else {"ran": False, "error": ""}))}
    ok = res["summary"]["fail"] == 0 and not live_err and not live_mis
    res["ok"] = ok

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"触发评测：{root}")
        print(f"触发话术 {len(rows)} 条")
        print()
        for f in findings:
            print(f"[{f['level']}] {f['rule']} {f['msg']}")
            if f["fix"]:
                print(f"        修法：{f['fix']}")
        if args.live:
            if live_err:
                print(f"\n真评测未执行：{live_err}")
            else:
                print(f"\n真评测：{len(live_mis)} 条未被判定为触发")
                for m in live_mis:
                    print(f"  - 「{m['say']}」-> {m['answer']}")
        s = res["summary"]
        print(f"\n结果：{'PASS' if ok else 'FAIL'}（离线 {s['fail']} FAIL / {s['warn']} WARN）")

    if live_err:
        return 2
    return 0 if ok else 1


def selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="trigeval_"))
    try:
        (tmp / "references").mkdir()
        (tmp / "scripts").mkdir()
        (tmp / "references" / "a.md").write_text("# A\n", encoding="utf-8")
        (tmp / "scripts" / "s.py").write_text("x=1\n", encoding="utf-8")

        # 正例
        good = (tmp / "SKILL.md")
        good.write_text(
            '---\nname: d\ndescription: "短剧 分镜 提示词 钩子 漫剧"\n---\n\n'
            '## 触发示例\n\n| 用户话术示例 | 落点 |\n|---|---|\n'
            '| 「做个短剧分镜」 | 08 段（`references/a.md`） |\n'
            '| 「写提示词」 | `scripts/s.py` |\n\n## 下一节\n',
            encoding="utf-8")
        desc, rows = parse_skill(good)
        assert len(rows) == 2, rows
        assert desc.startswith("短剧"), desc
        fs = check_offline(tmp, desc, rows)
        assert not [x for x in fs if x["level"] == "FAIL"], fs

        # 负例 1：落点引用不存在的文件 -> E3
        bad = tmp / "bad"
        (bad / "references").mkdir(parents=True)
        (bad / "SKILL.md").write_text(
            '---\nname: d\ndescription: "短剧"\n---\n\n## 触发示例\n\n'
            '| 话术 | 落点 |\n|---|---|\n| 「x」 | `references/ghost.md` |\n',
            encoding="utf-8")
        d2, r2 = parse_skill(bad / "SKILL.md")
        assert any(x["rule"] == "E3" for x in check_offline(bad, d2, r2))

        # 负例 2：落点空 -> E2
        bad2 = tmp / "bad2"
        bad2.mkdir()
        (bad2 / "SKILL.md").write_text(
            '---\nname: d\ndescription: "短剧"\n---\n\n## 触发示例\n\n'
            '| 话术 | 落点 |\n|---|---|\n| 「x」 |  |\n',
            encoding="utf-8")
        d3, r3 = parse_skill(bad2 / "SKILL.md")
        assert any(x["rule"] == "E2" for x in check_offline(bad2, d3, r3))

        # 负例 3：话术重复 -> E4
        bad3 = tmp / "bad3"
        bad3.mkdir()
        (bad3 / "SKILL.md").write_text(
            '---\nname: d\ndescription: "短剧"\n---\n\n## 触发示例\n\n'
            '| 话术 | 落点 |\n|---|---|\n| 「x」 | 01 段 |\n| 「x」 | 02 段 |\n',
            encoding="utf-8")
        d4, r4 = parse_skill(bad3 / "SKILL.md")
        assert any(x["rule"] == "E4" for x in check_offline(bad3, d4, r4))

        # 负例 4：描述缺关键词 -> E5 WARN
        bad4 = tmp / "bad4"
        bad4.mkdir()
        (bad4 / "SKILL.md").write_text(
            '---\nname: d\ndescription: "只有短剧"\n---\n\n## 触发示例\n\n'
            '| 话术 | 落点 |\n|---|---|\n| 「帮我调色」 | 10 段 |\n',
            encoding="utf-8")
        d5, r5 = parse_skill(bad4 / "SKILL.md")
        warns = [x for x in check_offline(bad4, d5, r5) if x["rule"] == "E5"]
        assert warns, "调色 未在 description，应告警"

        # 负例 5：无触发表 -> E1
        bad5 = tmp / "bad5"
        bad5.mkdir()
        (bad5 / "SKILL.md").write_text('---\nname: d\ndescription: "x"\n---\n# D\n',
                                       encoding="utf-8")
        d6, r6 = parse_skill(bad5 / "SKILL.md")
        assert any(x["rule"] == "E1" for x in check_offline(bad5, d6, r6))

        # 真评测缺通道时抛 RuntimeError（本机无 claude 时成立）
        if not shutil.which("claude"):
            try:
                run_live("d", [("x", "y")])
                raise AssertionError("缺通道时应抛 RuntimeError")
            except RuntimeError:
                pass

        print("selftest PASS（解析话术表 / 落点空·死链·重复·缺关键词·无表五类检出 / 缺通道拒绝假绿）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
