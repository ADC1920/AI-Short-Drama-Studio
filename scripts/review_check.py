# -*- coding: utf-8 -*-
"""审查记录格式机检（ai-short-drama-studio 技能）。

用途：审查规则表（references/review-rubric.md）管「该查什么」，本脚本只管
「审查记录本身是不是空壳」——不判断内容对错，只保证结论档位自洽、每条有证据、
证据不足时写清了缺什么。

用法：
  python scripts/review_check.py <审查记录.md>
  python scripts/review_check.py <项目目录>          # 检查 _reviews/ 下全部记录
  python scripts/review_check.py selftest

判据（对应 review-rubric.md 第七节，六条）：
  1 总结论存在且在四档内
  2 REVISE 时至少一条不通过
  3 PROVISIONAL 时至少一条证据不足，且该行证据列写了缺什么（≥6 字）
  4 APPROVE 时不允许存在不通过或证据不足
  5 每条有证据且非空
  6 审查人、审查时间、范围三项齐
"""
import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

VERDICTS = ("APPROVE", "APPROVE_WITH_NOTES", "REVISE", "PROVISIONAL")
ROW_PASS = ("通过", "PASS", "pass")
ROW_FAIL = ("不通过", "FAIL", "fail")
ROW_NA = ("证据不足", "无法判定", "PROVISIONAL")
RULE_ID_RE = re.compile(r"^RA-[SABPF]-\d{2}$")


def read_text_any(path: Path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: 无法按 UTF-8/GBK 解码")


def parse(text: str):
    """抽出总结论、逐条表、元信息。返回 dict。"""
    out = {"verdict": "", "verdicts_raw": [], "rows": [], "meta": {},
           "has_section": False}
    lines = text.splitlines()
    # 结论区：## 结论 之后的第一个非空非标题行
    for i, ln in enumerate(lines):
        if ln.strip().startswith("## ") and "结论" in ln:
            out["has_section"] = True
            for nxt in lines[i + 1:]:
                s = nxt.strip()
                if not s or s.startswith("#"):
                    continue
                out["verdict"] = s.strip("`* ")
                break
            break
    # 元信息：- 审查人：xxx
    for ln in lines:
        m = re.match(r"^[-*]\s*(审查人|审查时间|范围)\s*[：:]\s*(.*)$", ln.strip())
        if m:
            out["meta"][m.group(1)] = m.group(2).strip()
    # 逐条表：| RA-S-01 | 通过 | 证据 |
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if not RULE_ID_RE.match(cells[0]):
            continue
        out["rows"].append({"rule": cells[0], "verdict": cells[1],
                            "evidence": "|".join(cells[2:]).strip()})
    return out


def classify(verdict_text: str):
    """把条目结论归类为 pass / fail / na / unknown。"""
    v = verdict_text.strip()
    if any(k in v for k in ROW_NA):
        return "na"
    if any(k in v for k in ROW_FAIL):
        return "fail"
    if any(k in v for k in ROW_PASS):
        return "pass"
    return "unknown"


def check_file(path: Path):
    """返回 (errors, warnings)。errors 非空即不通过。"""
    errors, warns = [], []
    try:
        text = read_text_any(path)
    except (ValueError, OSError) as e:
        return [f"无法读取：{e}"], []
    p = parse(text)
    if not p["has_section"]:
        errors.append("缺「## 结论」节")
    if not p["verdict"]:
        errors.append("总结论为空")
    elif p["verdict"] not in VERDICTS:
        errors.append(f"总结论 {p['verdict']!r} 不在四档内（{'/'.join(VERDICTS)}）")
    if not p["rows"]:
        errors.append("无逐条表（需要 | 编号 | 结论 | 证据 | 三列，编号形如 RA-S-01）")

    kinds = [classify(r["verdict"]) for r in p["rows"]]
    n_pass = kinds.count("pass")
    n_fail = kinds.count("fail")
    n_na = kinds.count("na")
    n_unk = kinds.count("unknown")

    # 规则 5：每条有证据
    for r in p["rows"]:
        if not r["evidence"]:
            errors.append(f"{r['rule']} 缺证据列")
    if n_unk:
        bad = [r["rule"] for r, k in zip(p["rows"], kinds) if k == "unknown"]
        errors.append("结论无法识别（应为 通过/不通过/证据不足）：" + "、".join(bad))

    # 规则 2/3/4：档位自洽
    v = p["verdict"]
    if v == "REVISE" and n_fail == 0:
        errors.append("总结论 REVISE 但逐条无「不通过」条目")
    if v == "PROVISIONAL":
        if n_na == 0:
            errors.append("总结论 PROVISIONAL 但逐条无「证据不足」条目")
        else:
            thin = [r["rule"] for r, k in zip(p["rows"], kinds)
                    if k == "na" and len(r["evidence"]) < 6]
            if thin:
                errors.append("证据不足的条目未写明缺什么（证据列少于 6 字）："
                              + "、".join(thin))
    if v == "APPROVE" and (n_fail or n_na):
        errors.append("总结论 APPROVE 但存在不通过或证据不足的条目")

    # 规则 6：元信息三项
    for key in ("审查人", "审查时间", "范围"):
        if not p["meta"].get(key):
            errors.append(f"缺元信息：{key}")

    # 警告级：审查人写了「已检查」这类无信息量证据
    for r in p["rows"]:
        if classify(r["verdict"]) == "pass" and r["evidence"] in ("已检查", "已看", "OK", "ok"):
            warns.append(f"{r['rule']} 证据无信息量（{r['evidence']}）——写清看了什么")
    if n_pass and not n_fail and not n_na:
        pass
    return errors, warns


def review_files(src: Path):
    if src.is_file():
        return [src]
    d = src / "_reviews"
    if d.is_dir():
        return sorted(p for p in d.glob("*.md") if p.is_file())
    return []


def run(src: Path):
    files = review_files(src)
    if not files:
        print(f"未找到审查记录：{src}（项目模式查 _reviews/*.md）")
        return 2
    total_err = 0
    for f in files:
        errors, warns = check_file(f)
        label = f.name if src.is_dir() else str(f)
        if errors:
            total_err += len(errors)
            print(f"FAIL {label}")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"PASS {label}")
        for w in warns:
            print(f"  警告 {w}")
    if total_err:
        print(f"\n汇总：{total_err} 项待修（共 {len(files)} 份记录）")
        return 1
    print(f"\n汇总：全部通过（{len(files)} 份记录）")
    return 0


def sample_record(verdict="APPROVE_WITH_NOTES", with_na=False):
    rows = [
        ("RA-S-01", "通过", "check_script.py exit 0"),
        ("RA-S-04", "通过", "check_script.py S5/S6 无错，钩子行 18 字"),
        ("RA-B-05", "证据不足" if with_na else "通过",
         "未查看 组03 定稿图，缺该镜首帧" if with_na else "逐镜看过 9 张定稿图，构图与光位一致"),
    ]
    body = "\n".join(f"| {r} | {v} | {e} |" for r, v, e in rows)
    return f"""# 审查记录 · 测试

- 审查人：selftest
- 审查时间：2026-11-12 20:00:00
- 范围：RA-S / RA-B

## 结论

{verdict}

## 逐条

| 编号 | 结论 | 证据 |
|---|---|---|
{body}
"""


def selftest():
    tmp = Path(tempfile.mkdtemp(prefix="rc_st_"))
    try:
        # 1 合规记录通过
        good = tmp / "good.md"
        good.write_text(sample_record(), encoding="utf-8", newline="\n")
        e, w = check_file(good)
        assert not e, e

        # 2 缺证据行 → 报错
        bad = tmp / "bad.md"
        bad.write_text(sample_record().replace("| check_script.py exit 0 |", "|  |"),
                       encoding="utf-8", newline="\n")
        e, _ = check_file(bad)
        assert any("缺证据" in x for x in e), e

        # 3 PROVISIONAL 但无证据不足条目 → 报错
        prov = tmp / "prov.md"
        prov.write_text(sample_record("PROVISIONAL"), encoding="utf-8", newline="\n")
        e, _ = check_file(prov)
        assert any("无「证据不足」条目" in x for x in e), e

        # 4 证据不足但没写缺什么 → 报错
        thin = tmp / "thin.md"
        thin.write_text(sample_record("PROVISIONAL", with_na=True).replace(
            "未查看 组03 定稿图，缺该镜首帧", "没看"), encoding="utf-8", newline="\n")
        e, _ = check_file(thin)
        assert any("未写明缺什么" in x for x in e), e

        # 5 APPROVE 但有证据不足 → 报错
        ap = tmp / "ap.md"
        ap.write_text(sample_record("APPROVE", with_na=True), encoding="utf-8", newline="\n")
        e, _ = check_file(ap)
        assert any("APPROVE 但存在" in x for x in e), e

        # 6 REVISE 但无不通过条目 → 报错
        rev = tmp / "rev.md"
        rev.write_text(sample_record("REVISE"), encoding="utf-8", newline="\n")
        e, _ = check_file(rev)
        assert any("REVISE 但逐条无「不通过」" in x for x in e), e

        # 7 REVISE 且有不通过条目 → 通过
        rev2 = tmp / "rev2.md"
        rev2.write_text(sample_record("REVISE").replace(
            "| RA-S-04 | 通过 |", "| RA-S-04 | 不通过 |"), encoding="utf-8", newline="\n")
        e, _ = check_file(rev2)
        assert not e, e

        # 8 总结论不在四档 → 报错
        inv = tmp / "inv.md"
        inv.write_text(sample_record("基本通过"), encoding="utf-8", newline="\n")
        e, _ = check_file(inv)
        assert any("不在四档内" in x for x in e), e

        # 9 缺元信息 → 报错
        nm = tmp / "nm.md"
        nm.write_text(sample_record().replace("- 审查人：selftest\n", ""),
                      encoding="utf-8", newline="\n")
        e, _ = check_file(nm)
        assert any("审查人" in x for x in e), e

        # 10 项目模式：_reviews/ 多份
        proj = tmp / "项目"
        (proj / "_reviews").mkdir(parents=True)
        (proj / "_reviews" / "第1集.md").write_text(sample_record(), encoding="utf-8")
        (proj / "_reviews" / "第2集.md").write_text(sample_record("REVISE"),
                                                    encoding="utf-8")
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(proj)
        assert rc == 1, "有不合规记录应返回 1"
        out = buf.getvalue()
        assert "PASS 第1集.md" in out and "FAIL 第2集.md" in out, out

        # 11 无记录 → 返回 2
        empty = tmp / "空项目"
        empty.mkdir()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(empty)
        assert rc == 2, rc

        print("selftest PASS（11 项：合规/缺证据/PROVISIONAL 自洽/证据不足写明/"
              "APPROVE 冲突/REVISE 自洽×2/结论越界/缺元信息/项目模式/无记录）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
        return
    ap = argparse.ArgumentParser(description="审查记录格式机检")
    ap.add_argument("src", help="审查记录 md 或项目目录（查 _reviews/*.md）")
    args = ap.parse_args()
    sys.exit(run(Path(args.src)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
