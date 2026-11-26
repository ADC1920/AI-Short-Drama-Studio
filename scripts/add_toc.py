# -*- coding: utf-8 -*-
"""给 references/*.md 批量插入目录（TOC）——一次性维护脚本。

官方 Agent Skills 最佳实践：超过 100 行的 reference 应在顶部给目录，
否则 agent 用 head 预览时只见到片段、看不到全文范围。

插入位置：第一个 `## ` 标题之前（保留 `# 标题` 与 `> 何时读` 引言块）。
幂等：已有 `## 目录` 的文件跳过。

用法：
  python scripts/add_toc.py --dry-run     # 看会改哪些
  python scripts/add_toc.py               # 执行
  python scripts/add_toc.py --min-lines 150
  python scripts/add_toc.py --selftest
"""
import argparse
import re
import sys
from pathlib import Path

TOC_MARK = "## 目录"


def anchor(text):
    """GitHub 风格锚点：小写、去标点、空格转连字符。中文保留。"""
    t = text.strip().lower()
    t = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", t)
    t = re.sub(r"\s+", "-", t)
    return t


def collect_headings(lines):
    """抽出所有 `## ` 级标题（不含 ###），返回 [(原文, 锚点)]。"""
    out = []
    for ln in lines:
        m = re.match(r"^##\s+(.+?)\s*$", ln)
        if m and not m.group(1).startswith("目录"):
            title = m.group(1)
            out.append((title, anchor(title)))
    return out


def insert_toc(text, min_lines):
    """返回 (新文本, 是否改动, 原因)。"""
    lines = text.splitlines()
    if len(lines) <= min_lines:
        return text, False, "行数未达阈值"
    if TOC_MARK in text:
        return text, False, "已有目录"
    heads = collect_headings(lines)
    if len(heads) < 2:
        return text, False, "标题不足两个"

    # 找插入点：第一个 ## 标题的行号
    insert_at = None
    for i, ln in enumerate(lines):
        if re.match(r"^##\s+", ln) and not ln.startswith("## 目录"):
            insert_at = i
            break
    if insert_at is None:
        return text, False, "找不到插入点"

    toc = [TOC_MARK, ""]
    for title, anc in heads:
        toc.append(f"- [{title}](#{anc})")
    toc.append("")

    new_lines = lines[:insert_at] + toc + lines[insert_at:]
    return "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), True, f"插入 {len(heads)} 条"


def main():
    ap = argparse.ArgumentParser(description="给 references 批量加目录")
    ap.add_argument("--dir", default="references", help="目标目录（默认 references）")
    ap.add_argument("--min-lines", type=int, default=100, help="超过此行数才加（默认 100）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    d = Path(args.dir)
    if not d.is_dir():
        print(f"目录不存在：{d}")
        return 2

    changed = skipped = 0
    for f in sorted(d.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        new, did, why = insert_toc(text, args.min_lines)
        if did:
            changed += 1
            print(f"{'[干跑] ' if args.dry_run else ''}改 {f.name}：{why}")
            if not args.dry_run:
                f.write_text(new, encoding="utf-8")
        else:
            skipped += 1
    print(f"\n合计：{changed} 改 / {skipped} 跳过" + ("（干跑）" if args.dry_run else ""))
    return 0


def selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="toc_"))
    try:
        f = tmp / "a.md"
        body = "# 标题\n\n> 何时读：某事时。\n\n## 一节\n\n内容\n\n## 二节：带标点！\n\n内容\n"
        f.write_text(body, encoding="utf-8")
        # 行数未达阈值 -> 不改
        new, did, _ = insert_toc(body, 100)
        assert not did
        # 达阈值 -> 插入
        new, did, _ = insert_toc(body, 5)
        assert did, "应插入"
        assert TOC_MARK in new
        assert "- [一节](#一节)" in new, new
        # 链接文字保留原标题，锚点去标点
        assert "- [二节：带标点！](#二节带标点)" in new, new
        # 位置：在第一个 ## 之前
        assert new.index(TOC_MARK) < new.index("## 一节")
        # 幂等
        new2, did2, _ = insert_toc(new, 5)
        assert not did2 and new2 == new
        # 标题不足两个不改
        few = "# 标题\n\n## 只有一节\n\n内容\n"
        _, did3, _ = insert_toc(few, 1)
        assert not did3
        print("selftest PASS（阈值/插入/锚点/位置/幂等/标题不足六项）")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
