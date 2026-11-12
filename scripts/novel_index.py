# -*- coding: utf-8 -*-
"""原著长文结构索引（ai-short-drama-studio 技能）。

职责边界（重要）：本脚本只做**结构化提取**，不做创作判断。
  - 做：编码识别、章节切分、字数与偏移、情节点候选抽取、分集章节区间建议。
  - 不做：改编价值判断、题材爽点、钩子设计、剧本生成——这些用 onlyshot-drama 技能。
  代码里用创作词黑名单锁住这条边界（见 CREATIVE_WORDS 与 selftest 第 6 项）。

数据文件：<项目>/_novel/index.json

用法：
  python scripts/novel_index.py index <原著txt> [--out _novel/index.json] [--chapters 1-5]
  python scripts/novel_index.py candidates <项目> --episodes 24 [--json]
  python scripts/novel_index.py selftest

约定：
  - 每个情节点带 quote 与 offset，可用 start+offset 回查原文（取出的字符串必须等于 quote）。
  - 超过 200KB 只出章节骨架，提示分批；不在一次调用里读入全部正文。
  - 章节标题识别失败时明确报错，不硬切。
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

NOVEL_DIR = "_novel"
INDEX_NAME = "index.json"
BIG_FILE_BYTES = 200 * 1024
MAX_POINTS_PER_CHAPTER = 40

# 章节标题形态（按优先级尝试）。识别失败即报错，不按字数硬切。
CHAPTER_PATTERNS = [
    re.compile(r"^\s*第\s*([0-9零一二三四五六七八九十百千]+)\s*[章回节]\s*(.*)$"),
    re.compile(r"^\s*Chapter\s+(\d+)\b(.*)$", re.I),
    re.compile(r"^\s*(\d+)[.、]\s*(\S.*)$"),
]

# 创作词黑名单：candidates 的输出里不得出现，防止职责越界到 onlyshot-drama
CREATIVE_WORDS = ("钩子", "爽点", "反转", "卖点", "爆点", "高能", "节奏设计",
                  "人物弧光", "题材", "受众", "钩子点")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_text_with_encoding(path: Path):
    """按 UTF-8 / GBK 依次尝试，返回 (文本, 编码名)。与 check_script 同策略。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: 无法按 UTF-8/GBK 解码")


def find_chapter_heads(lines):
    """返回 [(行号, 编号原文, 标题)]。识别不到返回空列表。"""
    heads = []
    for i, ln in enumerate(lines):
        if len(ln) > 80:      # 长行不可能是章节标题
            continue
        for pat in CHAPTER_PATTERNS:
            m = pat.match(ln)
            if m:
                heads.append((i, m.group(1), ln.strip()))
                break
    return heads


def split_chapters(text):
    """按章节标题切分，返回 [(no, title, start_char, end_char)]。

    用字符偏移而非行号，保证 quote 回查可用。
    """
    lines = text.splitlines(keepends=True)
    heads = find_chapter_heads(lines)
    if not heads:
        return []
    # 行首字符偏移表
    starts, acc = [], 0
    for ln in lines:
        starts.append(acc)
        acc += len(ln)
    total = len(text)
    chapters = []
    for idx, (lineno, no_text, title) in enumerate(heads):
        start = starts[lineno]
        end = starts[heads[idx + 1][0]] if idx + 1 < len(heads) else total
        chapters.append({
            "no": idx + 1,
            "no_text": no_text,
            "title": title,
            "start": start,
            "end": end,
            "chars": end - start,
        })
    return chapters


def extract_points(text, chapter):
    """从一章里抽情节点候选：按段落切，每段取首句作 quote。

    只做机械切分，不判断哪段重要——重要性判断属于创作层。
    """
    body = text[chapter["start"]:chapter["end"]]
    points = []
    # 段 = 连续非空行块
    for m in re.finditer(r"(?:[^\n]*\n?)+?(?=\n\s*\n|\Z)", body):
        para = m.group(0).strip()
        if not para or para == chapter["title"].strip():
            continue
        # 首句：到第一个句末标点
        q = re.split(r"[。！？!?…]", para, maxsplit=1)[0].strip()
        if len(q) < 4:
            continue
        offset = chapter["start"] + m.start()
        points.append({
            "id": f"P{len(points)+1:03d}",
            "quote": q[:80],
            "offset": offset,
            "kind": "对话" if re.search(r"[「“\"].+[」”\"]", para) else "叙述",
        })
        if len(points) >= MAX_POINTS_PER_CHAPTER:
            break
    return points


def build_index(novel: Path, chapter_range=None):
    """建索引。chapter_range=(起, 止) 时只处理该区间的情节点（大文件分批用）。"""
    if not novel.is_file():
        raise FileNotFoundError(f"原著不存在：{novel}")
    size = novel.stat().st_size
    text, encoding = read_text_with_encoding(novel)
    chapters = split_chapters(text)
    if not chapters:
        raise ValueError("未识别到章节结构——请检查标题形态（第X章/Chapter N/N.）"
                         "或先手工切分章节")
    lo, hi = chapter_range or (1, len(chapters))
    big = size > BIG_FILE_BYTES and chapter_range is None
    out_chapters = []
    for ch in chapters:
        item = dict(ch)
        if lo <= ch["no"] <= hi and not big:
            item["points"] = extract_points(text, ch)
        else:
            item["points"] = []
        out_chapters.append(item)
    read_range = (f"第{lo}-{hi}章（全）" if (lo, hi) == (1, len(chapters))
                  else f"第{lo}-{hi}章")
    unread = [c["no"] for c in chapters if not (lo <= c["no"] <= hi)]
    return {
        "source": novel.name,
        "source_path": str(novel),
        "chars": len(text),
        "bytes": size,
        "encoding": encoding,
        "indexed": now(),
        "chapter_count": len(chapters),
        "read_range": read_range,
        "unread": unread,
        "skipped_points": big,
        "chapters": out_chapters,
    }


def load_index(root: Path):
    p = root / NOVEL_DIR / INDEX_NAME
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def episode_candidates(index, episodes: int):
    """把章节按字数切成 episodes 段，给章节区间建议。

    只给结构性区间，不含任何创作判断——输出的每个 field 都必须过 CREATIVE_WORDS 检查。
    """
    chs = index["chapters"]
    total_chars = sum(c["chars"] for c in chs) or 1
    target = total_chars / max(1, episodes)
    groups, cur, acc = [], [], 0
    for c in chs:
        cur.append(c["no"])
        acc += c["chars"]
        if acc >= target and len(groups) < episodes - 1:
            groups.append(cur)
            cur, acc = [], 0
    if cur:
        groups.append(cur)
    return {
        "episodes_requested": episodes,
        "episodes_planned": len(groups),
        "total_chars": total_chars,
        "avg_chars_per_episode": round(total_chars / max(1, len(groups)), 1),
        "ranges": [
            {"episode": i + 1,
             "chapters": f"第{g[0]}-{g[-1]}章" if len(g) > 1 else f"第{g[0]}章",
             "chapter_numbers": g,
             "chars": sum(next(c["chars"] for c in chs if c["no"] == n) for n in g)}
            for i, g in enumerate(groups)
        ],
    }


def assert_no_creative_words(payload):
    """职责边界断言：candidates 输出不得含创作判断词。"""
    text = json.dumps(payload, ensure_ascii=False)
    hits = [w for w in CREATIVE_WORDS if w in text]
    if hits:
        raise AssertionError(f"candidates 输出含创作词，越界到创作层：{hits}")


def cmd_index(args):
    novel = Path(args.novel)
    rng = None
    if args.chapters:
        try:
            lo, _, hi = args.chapters.partition("-")
            rng = (int(lo), int(hi or lo))
        except ValueError:
            print(f"--chapters 格式应为 起-止，如 1-5（收到 {args.chapters}）")
            return 2
    try:
        data = build_index(novel, rng)
    except (FileNotFoundError, ValueError, OSError) as e:
        print(str(e))
        return 2
    out = Path(args.out) if args.out else (Path(novel).parent / NOVEL_DIR / INDEX_NAME)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"已建原著索引：{out}")
    print(f"  {data['source']} · {data['chars']} 字 · {data['encoding']} · "
          f"{data['chapter_count']} 章 · 已分析 {data['read_range']}")
    if data["skipped_points"]:
        print(f"  正文 {data['bytes']//1024}KB 超过 200KB 上限：本次只出章节骨架，"
              f"情节点请分批 --chapters 1-5 补")
    else:
        n = sum(len(c["points"]) for c in data["chapters"])
        print(f"  情节点候选 {n} 个（每个带 quote 与 offset，可回查原文）")
    if data["unread"]:
        print(f"  未分析章节：{len(data['unread'])} 章（"
              + ("、".join(str(x) for x in data["unread"][:10])) + "）")
    print("  提醒：本脚本只做结构提取；选题、爽点、钩子设计用 onlyshot-drama 技能")
    return 0


def cmd_candidates(args):
    root = Path(args.root)
    index = load_index(root)
    if index is None:
        print(f"未找到原著索引：{root / NOVEL_DIR / INDEX_NAME}（先跑 index）")
        return 2
    res = episode_candidates(index, args.episodes)
    try:
        assert_no_creative_words(res)
    except AssertionError as e:
        print(f"内部错误：{e}")
        return 3
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    print(f"分集章节区间建议（{res['episodes_planned']} 集，"
          f"每集约 {res['avg_chars_per_episode']} 字）：")
    for r in res["ranges"]:
        print(f"  第{r['episode']:>2}集  {r['chapters']:<14}{r['chars']:>6} 字")
    if res["episodes_planned"] < res["episodes_requested"]:
        print(f"  注意：章节数不足以切成 {res['episodes_requested']} 集，实际 {res['episodes_planned']} 集")
    print("  本输出只有章节区间，不含剧情/钩子/爽点建议——创作判断用 onlyshot-drama")
    return 0


def selftest():
    tmp = Path(tempfile.mkdtemp(prefix="ni_st_"))
    try:
        # 造 20 章、每章约 200 字的合成原著
        para = ("他推开门，屋里空无一人。桌上放着一封没有署名的信。"
                "「你终于来了。」身后传来声音。他握紧了手里的刀。" * 3)
        chunks = [f"第{i}章 测试标题{i}\n\n{para}\n\n{para}\n\n" for i in range(1, 21)]
        novel = tmp / "原著.txt"
        novel.write_text("".join(chunks), encoding="utf-8", newline="\n")

        data = build_index(novel)
        # 1 章节切分正确
        assert data["chapter_count"] == 20, data["chapter_count"]
        assert data["chars"] == len(novel.read_text(encoding="utf-8"))
        total = sum(c["chars"] for c in data["chapters"])
        assert total == data["chars"], f"各章字数合计 {total} 应等于全文 {data['chars']}"
        # 2 各章 start/end 连续无重叠
        for a, b in zip(data["chapters"], data["chapters"][1:]):
            assert a["end"] == b["start"], (a["no"], a["end"], b["start"])
        # 3 情节点可回查原文（逐字相等）
        text = novel.read_text(encoding="utf-8")
        checked = 0
        for ch in data["chapters"]:
            for pt in ch["points"]:
                got = text[pt["offset"]:pt["offset"] + len(pt["quote"])]
                assert got == pt["quote"], f"回查不符：{got!r} != {pt['quote']!r}"
                checked += 1
        assert checked > 0, "未抽出任何情节点"

        # 4 GBK 与 UTF-8 同内容 → 章节数与字数一致
        gbk = tmp / "原著gbk.txt"
        gbk.write_bytes("".join(chunks).encode("gbk"))
        d2 = build_index(gbk)
        assert d2["encoding"] == "gbk", d2["encoding"]
        assert d2["chapter_count"] == data["chapter_count"]
        assert d2["chars"] == data["chars"]

        # 5 大文件只出骨架
        big = tmp / "大文件.txt"
        big.write_text("".join(chunks), encoding="utf-8")
        # 直接构造超 200KB 的输入
        big.write_text("".join(chunks) * 12, encoding="utf-8", newline="\n")
        assert big.stat().st_size > BIG_FILE_BYTES
        d3 = build_index(big)
        assert d3["skipped_points"] is True, "大文件应只出骨架"
        assert all(not c["points"] for c in d3["chapters"])

        # 5b 大文件分批时正常抽点
        d3b = build_index(big, (1, 3))
        assert d3b["skipped_points"] is False
        assert d3b["read_range"] == "第1-3章"
        assert d3b["unread"], "应记未分析章节"
        assert any(c["points"] for c in d3b["chapters"] if c["no"] <= 3)

        # 6 分集候选不越界：无创作词
        cand = episode_candidates(data, 24)
        assert_no_creative_words(cand)   # 不抛异常即合规
        assert cand["episodes_planned"] <= 24
        assert "ranges" in cand and cand["ranges"]
        # 反向验证黑名单有效：塞一个创作词必须被抓
        try:
            assert_no_creative_words({"x": "这集钩子要强"})
            raise AssertionError("黑名单未生效")
        except AssertionError as e:
            assert "越界" in str(e)

        # 7 章节识别失败明确报错
        plain = tmp / "无章节.txt"
        plain.write_text("这是一段没有任何章节标题的连续文本。" * 50,
                         encoding="utf-8", newline="\n")
        try:
            build_index(plain)
            raise AssertionError("无章节结构应报错")
        except ValueError as e:
            assert "未识别到章节结构" in str(e)

        # 8 命令行项目模式
        proj = tmp / "项目"
        (proj / NOVEL_DIR).mkdir(parents=True)
        (proj / NOVEL_DIR / INDEX_NAME).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_candidates(argparse.Namespace(root=str(proj), episodes=8, json=False))
        assert rc == 0, rc
        out = buf.getvalue()
        assert "分集章节区间建议" in out, out
        assert "onlyshot-drama" in out, "应提示创作层归属"

        print("selftest PASS（8 项：章节切分/偏移连续/情节点可回查/编码兼容/"
              "大文件骨架/分批抽点/创作词黑名单/无章节报错）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
        return
    ap = argparse.ArgumentParser(description="原著长文结构索引")
    sub = ap.add_subparsers(dest="cmd")
    p1 = sub.add_parser("index", help="建结构索引")
    p1.add_argument("novel", help="原著 txt")
    p1.add_argument("--out", default="", help="输出路径，默认 <原著目录>/_novel/index.json")
    p1.add_argument("--chapters", default="", help="只分析某区间，如 1-5")
    p2 = sub.add_parser("candidates", help="分集章节区间建议")
    p2.add_argument("root", help="项目目录")
    p2.add_argument("--episodes", type=int, default=24)
    p2.add_argument("--json", action="store_true")
    sub.add_parser("selftest", help="自检")
    args = ap.parse_args()
    if args.cmd == "index":
        sys.exit(cmd_index(args))
    elif args.cmd == "candidates":
        sys.exit(cmd_candidates(args))
    else:
        ap.print_help()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
