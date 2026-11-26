# -*- coding: utf-8 -*-
"""技能自身体检：front-matter 合规、引用完整性、索引覆盖、reference 体量。

与其余脚本的分工：它们查「项目产物」，本脚本查「技能本体」——技能自身的规范是否被遵守。
之前 28 个脚本全在查产物，没有一处能发现自己 SKILL.md 的 front-matter 违规。

用法：
  python scripts/check_skill.py                  # 体检当前仓库（脚本所在目录的上级）
  python scripts/check_skill.py <技能目录>        # 体检指定技能目录
  python scripts/check_skill.py --json           # 机读输出 {ok, findings[], summary}
  python scripts/check_skill.py --selftest       # 自检

检查项（K 系列）：
  K1 SKILL.md 存在且 front-matter 为合法 YAML 字典
  K2 front-matter 顶层键都在官方白名单内
     （name / description / license / allowed-tools / metadata / compatibility）
  K3 name 为 kebab-case、≤64 字符、无首尾连字符与连续连字符
  K4 description 非空、≤1024 字符、不含尖括号
  K5 SKILL.md 正文行数 <500（超出只告警，不阻断）
  K6 references/ 下每个 .md 都被 SKILL.md 直接引用（一层深，无孤儿）
  K7 每个 >100 行的 reference 顶部有目录（TOC）
  K8 scripts/ 下每个 .py 都在 SKILL.md 索引表里出现
  K9 索引表里提到的 references/*.md 与 scripts/*.py 都真实存在（无死链）

退出码：0 全部通过 / 1 有 FAIL / 2 用法或路径错误
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 官方 anthropics/skills 的 quick_validate.py 白名单
ALLOWED_FM = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
KEBAB_RE = re.compile(r"^[a-z0-9-]+$")
MAX_NAME = 64
MAX_DESC = 1024
MAX_BODY_LINES = 500
TOC_MIN_LINES = 100
# K7 豁免：整篇是「待复制进对话」的提示词正文，加目录会污染提示词本身
TOC_EXEMPT = {"agent-prompt.md"}


def finding(level, rule, msg, fix=""):
    """统一的 findings 条目：level=FAIL/WARN，rule=K 编号。"""
    return {"level": level, "rule": rule, "msg": msg, "fix": fix}


def parse_frontmatter(text):
    """返回 (dict 或 None, 错误消息)。不依赖 PyYAML——只解析顶层 key: value。"""
    if not text.startswith("---"):
        return None, "SKILL.md 未以 --- 开头（无 front-matter）"
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return None, "front-matter 格式不合法（缺结束 ---）"
    fm = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        mm = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if mm and mm.group(1) not in fm:
            fm[mm.group(1)] = mm.group(2)
        # 缩进行（metadata 下的子键）不当作顶层键
    return fm, ""


def strip_quotes(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def check_skill(root):
    """返回 findings 列表。root 必须是技能目录。"""
    out = []
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        out.append(finding("FAIL", "K1", "SKILL.md 不存在", "确认传入的是技能目录"))
        return out

    text = skill_md.read_text(encoding="utf-8", errors="replace")
    fm, err = parse_frontmatter(text)
    if err:
        out.append(finding("FAIL", "K1", err, "front-matter 首行 --- / 末行 --- 成对"))
        return out

    # K2 白名单
    unexpected = sorted(set(fm) - ALLOWED_FM)
    if unexpected:
        out.append(finding(
            "FAIL", "K2",
            f"front-matter 顶层键不在官方白名单：{', '.join(unexpected)}",
            f"移入 metadata 下，或只用：{', '.join(sorted(ALLOWED_FM))}"))

    # K3 name
    name = strip_quotes(fm.get("name", ""))
    if not name:
        out.append(finding("FAIL", "K3", "缺 name 字段", "补 name: <kebab-case>"))
    else:
        if not KEBAB_RE.match(name):
            out.append(finding("FAIL", "K3", f"name 含非法字符：{name!r}", "只用小写字母、数字、连字符"))
        if name.startswith("-") or name.endswith("-") or "--" in name:
            out.append(finding("FAIL", "K3", f"name 首尾有连字符或含连续连字符：{name!r}", "改成单连字符分隔"))
        if len(name) > MAX_NAME:
            out.append(finding("FAIL", "K3", f"name 过长 {len(name)} > {MAX_NAME}", "缩短"))

    # K4 description
    desc = strip_quotes(fm.get("description", ""))
    if not desc:
        out.append(finding("FAIL", "K4", "缺 description 字段", "补 description（写清做什么 + 何时用）"))
    else:
        if len(desc) > MAX_DESC:
            out.append(finding("FAIL", "K4", f"description 过长 {len(desc)} > {MAX_DESC}", "精简触发词"))
        if "<" in desc or ">" in desc:
            out.append(finding("FAIL", "K4", "description 含尖括号", "删除 < >"))

    # K5 正文行数
    body_lines = len(text.splitlines())
    if body_lines >= MAX_BODY_LINES:
        out.append(finding("WARN", "K5", f"SKILL.md {body_lines} 行 ≥ {MAX_BODY_LINES}",
                           "拆分长节到 references/ 并留指针"))

    # K6 孤儿 reference
    ref_dir = root / "references"
    if ref_dir.is_dir():
        for f in sorted(ref_dir.glob("*.md")):
            if f"references/{f.name}" not in text:
                out.append(finding("FAIL", "K6", f"reference 未被 SKILL.md 引用：{f.name}",
                                   "在索引表加一行，或删掉该文件"))

        # K7 >100 行 reference 的 TOC
        for f in sorted(ref_dir.glob("*.md")):
            if f.name in TOC_EXEMPT:
                continue
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            if len(lines) <= TOC_MIN_LINES:
                continue
            head = "\n".join(lines[:15])
            has_toc = bool(re.search(r"^##\s*(目录|Contents)", head, re.M)
                           or re.search(r"^\s*-\s*\[[^\]]+\]\(#", head, re.M))
            if not has_toc:
                out.append(finding(
                    "WARN", "K7",
                    f"{f.name} 有 {len(lines)} 行但顶部无目录",
                    "顶部加 ## 目录 + 各节锚点链接"))

    # K8 脚本索引覆盖
    script_dir = root / "scripts"
    if script_dir.is_dir():
        for f in sorted(script_dir.glob("*.py")):
            if f"scripts/{f.name}" not in text:
                out.append(finding("FAIL", "K8", f"脚本未进 SKILL.md 索引表：{f.name}",
                                   "在「参考文件与脚本索引」表加一行"))

    # K9 死链：索引里提到但文件不存在
    for m in re.finditer(r"references/([a-z0-9-]+\.md)", text):
        if not (ref_dir / m.group(1)).is_file():
            out.append(finding("FAIL", "K9", f"SKILL.md 引用了不存在的文件：references/{m.group(1)}",
                               "删掉该引用或补文件"))
    for m in re.finditer(r"scripts/([a-z0-9_]+\.py)", text):
        if not (script_dir / m.group(1)).is_file():
            out.append(finding("FAIL", "K9", f"SKILL.md 引用了不存在的脚本：scripts/{m.group(1)}",
                               "删掉该引用或补脚本"))

    # K10 CI workflow 必须是合法 YAML：未加引号的值里含「: 」会让整个 workflow 失效，
    # GitHub 只报「workflow file issue」不给行号，本地校验能省一轮 push 往返。
    # 无 PyYAML 时跳过（项目本身零依赖），有则校验。
    wf_dir = root / ".github" / "workflows"
    if wf_dir.is_dir():
        try:
            import yaml  # noqa: PLC0415 —— 可选依赖，按需导入
        except ImportError:
            yaml = None
        if yaml is not None:
            for f in sorted(wf_dir.glob("*.yml")):
                try:
                    yaml.safe_load(f.read_text(encoding="utf-8", errors="replace"))
                except yaml.YAMLError as e:
                    first = str(e).splitlines()[0] if str(e) else "YAML 解析失败"
                    out.append(finding("FAIL", "K10", f"{f.name} 不是合法 YAML：{first}",
                                       "给含冒号的值加引号，或用 | 块标量"))
    return out


def summarize(findings):
    fails = [x for x in findings if x["level"] == "FAIL"]
    warns = [x for x in findings if x["level"] == "WARN"]
    return {"total": len(findings), "fail": len(fails), "warn": len(warns)}


def run(root):
    findings = check_skill(root)
    summary = summarize(findings)
    return {"root": str(root), "ok": summary["fail"] == 0, "findings": findings, "summary": summary}


def selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="skillchk_"))
    try:
        # 正例：完全合规的最小技能
        good = tmp / "good"
        (good / "references").mkdir(parents=True)
        (good / "scripts").mkdir()
        (good / "references" / "a.md").write_text("# A\n", encoding="utf-8")
        (good / "scripts" / "s.py").write_text("print(1)\n", encoding="utf-8")
        (good / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: 做事。用 when needed.\n"
            "license: MIT\nmetadata:\n  version: 1.0.0\n---\n\n"
            "# Demo\n\n| `references/a.md` | 何时 |\n| `scripts/s.py` | 何时 |\n",
            encoding="utf-8")
        r = run(good)
        assert r["ok"], r["findings"]

        # 负例 1：version 放顶层 -> K2 FAIL
        bad = tmp / "bad1"
        bad.mkdir()
        (bad / "SKILL.md").write_text(
            "---\nname: demo\nversion: 1.0.0\ndescription: x\n---\n# D\n", encoding="utf-8")
        r = run(bad)
        assert not r["ok"], "version 顶层应判 FAIL"
        assert any(x["rule"] == "K2" for x in r["findings"]), r["findings"]

        # 负例 2：name 非法 -> K3
        bad2 = tmp / "bad2"
        bad2.mkdir()
        (bad2 / "SKILL.md").write_text(
            "---\nname: Bad_Name\ndescription: x\n---\n# D\n", encoding="utf-8")
        assert any(x["rule"] == "K3" for x in run(bad2)["findings"])

        # 负例 3：孤儿 reference -> K6
        bad3 = tmp / "bad3"
        (bad3 / "references").mkdir(parents=True)
        (bad3 / "references" / "orphan.md").write_text("# x\n", encoding="utf-8")
        (bad3 / "SKILL.md").write_text(
            "---\nname: d3\ndescription: x\n---\n# D\n", encoding="utf-8")
        assert any(x["rule"] == "K6" for x in run(bad3)["findings"])

        # 负例 4：脚本未进索引 -> K8
        bad4 = tmp / "bad4"
        (bad4 / "scripts").mkdir(parents=True)
        (bad4 / "scripts" / "lonely.py").write_text("x=1\n", encoding="utf-8")
        (bad4 / "SKILL.md").write_text(
            "---\nname: d4\ndescription: x\n---\n# D\n", encoding="utf-8")
        assert any(x["rule"] == "K8" for x in run(bad4)["findings"])

        # 负例 5：死链 -> K9
        bad5 = tmp / "bad5"
        bad5.mkdir()
        (bad5 / "SKILL.md").write_text(
            "---\nname: d5\ndescription: x\n---\n见 `references/ghost.md`\n", encoding="utf-8")
        assert any(x["rule"] == "K9" for x in run(bad5)["findings"])

        # 负例 6：长 reference 无 TOC -> K7 WARN
        bad6 = tmp / "bad6"
        (bad6 / "references").mkdir(parents=True)
        (bad6 / "references" / "long.md").write_text(
            "# 长文\n" + "行\n" * 120, encoding="utf-8")
        (bad6 / "SKILL.md").write_text(
            "---\nname: d6\ndescription: x\n---\n`references/long.md`\n", encoding="utf-8")
        r = run(bad6)
        assert any(x["rule"] == "K7" for x in r["findings"]), r["findings"]
        assert r["ok"], "K7 是 WARN，不该让整体判 FAIL"

        # 负例 7：CI workflow 非法 YAML（值里裸冒号）-> K10
        try:
            import yaml  # noqa: F401
            bad7 = tmp / "bad7"
            (bad7 / ".github" / "workflows").mkdir(parents=True)
            (bad7 / ".github" / "workflows" / "ci.yml").write_text(
                "name: ci\njobs:\n  a:\n    steps:\n"
                "      - name: Trigger eval (offline: description vs table)\n"
                "        run: echo hi\n", encoding="utf-8")
            (bad7 / "SKILL.md").write_text(
                "---\nname: d7\ndescription: x\n---\n# D\n", encoding="utf-8")
            assert any(x["rule"] == "K10" for x in run(bad7)["findings"]), "K10 应检出非法 YAML"
            # 正例：同内容加引号后应通过
            (bad7 / ".github" / "workflows" / "ci.yml").write_text(
                'name: ci\njobs:\n  a:\n    steps:\n'
                '      - name: "Trigger eval (offline - x)"\n'
                '        run: echo hi\n', encoding="utf-8")
            assert not any(x["rule"] == "K10" for x in run(bad7)["findings"]), "加引号后不该报 K10"
        except ImportError:
            pass  # 无 PyYAML 时跳过该用例

        print("selftest PASS（7 项：合规正例 / version 顶层 / name 非法 / 孤儿引用 / "
              "脚本漏索引 / 死链 / 长文无 TOC / CI YAML 非法）")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="技能自身体检（front-matter / 引用 / 索引 / 体量）")
    ap.add_argument("root", nargs="?", help="技能目录（默认取本脚本的上级目录）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--selftest", action="store_true", help="自检")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return 0
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"目录不存在：{root}")
        return 2

    res = run(root)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"技能体检：{res['root']}")
        print()
        for x in res["findings"]:
            print(f"[{x['level']}] {x['rule']} {x['msg']}")
            if x["fix"]:
                print(f"        修法：{x['fix']}")
        s = res["summary"]
        if not res["findings"]:
            print("PASS（无问题）")
        else:
            print(f"\n结果：{'PASS' if res['ok'] else 'FAIL'}（{s['fail']} FAIL / {s['warn']} WARN）")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
