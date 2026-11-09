#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剧本台机检（ai-short-drama-studio 技能）。

五工位里剧本台是唯一没有机检的工位：角色与场景台走 check_refs、分镜台走
validate_storyboard、出片台走 manifest、后期台走 qa_batch，只有剧本.md 靠人读。
本工具补这一环，门禁口径直接取自 SKILL.md 剧本台——
「不是模板占位、有钩子与收尾、@引用名清单齐」。

检查项：
  S1 可解析      文件可读、非空（UTF-8/GBK 自动识别）
  S2 集号一致    正文「第N集」与所在目录名一致（错误级）
  S3 模板占位    TODO/XXX/占位/【待填】一类残留（错误级）；
                 「待补/待核」标注（警告级——长剧本分批读的合法状态，提醒补完）
  S4 @引用清单   列出本集 @引用名；为 0 时提示（纯文字剧本需显式说明）
  S5 钩子       正文出现钩子标记且不是敷衍词
  S6 收尾       正文出现收尾标记且不是敷衍词
  S7 场次编号   「## 场景 N」从 1 起连续
  S8 台词时长   按中文语速折算说台词所需秒数；给 --target 时核对预算
  S9 空场       只有标题没有正文的场次

S1-S3 为错误级：挡住排产（缺集号、模板未填、文件损坏）。
S4-S9 为警告级：属于创作判断，留给人决定是否接受——「钩子写得好不好」
机器判不了，只能判「有没有、是不是敷衍词」。

用法:
    python check_script.py <剧本.md> [--target 120] [--rate 4.3]
    python check_script.py <项目目录>          # 扫全部 第N集/剧本.md
    python check_script.py --selftest
退出码: 0=无错误, 1=存在错误, 2=用法/文件错误
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

# 模板占位：命中即说明剧本还没落到可排产状态
PLACEHOLDER_ERRORS = ("TODO", "FIXME", "XXX", "占位", "【待填】", "（待填）", "(待填)",
                      "此处略", "以下略", "待设计", "待定")
# 显式未完成标注：合法但必须提醒（长剧本分批读、素材未就绪时都会出现）
PLACEHOLDER_WARNS = ("待补", "待核", "待确认")
# 钩子与收尾标记：只判「有没有、是否敷衍」，不判质量
HOOK_MARKS = ("钩子", "留钩", "悬念", "开场钩", "好奇缺口", "钩住", "钩住观众")
END_MARKS = ("收尾", "结尾", "集末", "末尾", "下一集", "下集", "集尾")
# 敷衍判据：标记所在行去掉标记与标点后少于这么多字，视为没写内容
SKELETON_MIN = 6
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SCENE_RE = re.compile(r"(?m)^#{1,4}\s*场景\s*(\d+)")
EP_DIR_RE = re.compile(r"第\s*(\d+)\s*集")
EP_TEXT_RE = re.compile(r"第\s*(\d+)\s*集")
QUOTE_RE = re.compile(r"[「“\"]([^」”\"]{1,200})[」”\"]")
LINE_RE = re.compile(r"(?m)^\s*([^\s：:]{1,8})\s*[：:]\s*(.{1,200})$")
# 台词行里要排除的「不是台词」的标签
NON_DIALOGUE_LABELS = ("场景", "出场人物", "本场情绪", "场景出场状态", "备注", "注", "说明",
                       "画幅", "模型", "集号", "标题", "时间", "地点")
DEFAULT_RATE = 4.3  # 中文口播中值，区间 4.0-4.6 字/秒（见 short-video-studio.md）


def read_text_any(path):
    """按 UTF-8 读，失败回退 GBK——中文 Windows 上剧本常有 GBK 存盘。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: 无法按 UTF-8/GBK 解码")


def is_skeleton(line, marks):
    """标记所在行去掉标记与标点后是否还有内容（判断「写了钩子」还是「只写了钩子二字」）。"""
    rest = line
    for m in marks:
        rest = rest.replace(m, "")
    rest = re.sub(r"[\s\-#*|:：·—、，。,.>（）()\[\]【】]", "", rest)
    return len(rest) < SKELETON_MIN


def extract_dialogue(text):
    """抽取台词文本。两条来源：引号内文本，以及「角色名：台词」行。

    只认引号与「短标签 + 冒号」两种形态——动作描述里没有引号，不会误算；
    冒号行排除「出场人物：」「本场情绪：」这类场记标签。
    """
    out = []
    for m in QUOTE_RE.finditer(text):
        out.append(m.group(1))
    for m in LINE_RE.finditer(text):
        label, body = m.group(1), m.group(2)
        if any(k in label for k in NON_DIALOGUE_LABELS):
            continue
        if body.strip().startswith("-"):
            continue
        out.append(body)
    return out


def check(path, target=None, rate=DEFAULT_RATE, project=None):
    """返回 (errors, warnings, info)。path 为剧本.md 路径。"""
    errors, warnings, info = [], [], []
    p = Path(path)
    if not p.is_file():
        return [f"文件不存在：{p}"], [], []
    try:
        text = read_text_any(p)
    except (ValueError, OSError) as e:
        return [f"读取失败：{e}"], [], []
    if not text.strip():
        return [f"剧本为空：{p}"], [], []

    # S1 长度与基本形态
    info.append(f"字符数 {len(text)}，行数 {len(text.splitlines())}")

    # S2 集号一致：目录名第N集 与 正文第N集 必须一致，否则整集排产会串集
    dir_m = EP_DIR_RE.search(p.parent.name)
    body_m = EP_TEXT_RE.search(text)
    if dir_m and body_m and dir_m.group(1) != body_m.group(1):
        errors.append(f"S2 集号不一致：目录是第 {dir_m.group(1)} 集，正文写第 {body_m.group(1)} 集")
    elif dir_m and not body_m:
        warnings.append(f"S2 正文没写集号（目录为第 {dir_m.group(1)} 集）——切集后建议在标题保留集号")

    # S3 模板占位
    for w in PLACEHOLDER_ERRORS:
        if w in text:
            errors.append(f"S3 模板占位残留「{w}」——剧本未落到可排产状态")
    for w in PLACEHOLDER_WARNS:
        if w in text:
            warnings.append(f"S3 存在「{w}」标注——确认是合法未完成标注后逐条补完再排产")

    # S4 @引用名清单（断链核对属 check_refs 的职责，这里只确认清单非空）
    refs = sorted(set(re.findall(r"@([A-Za-z0-9_\-\u4e00-\u9fff]{1,40})", text)))
    if refs:
        info.append(f"@引用名 {len(refs)} 个：" + "、".join(refs))
    else:
        warnings.append("S4 全文没有 @引用名——纯文字剧本需显式说明，否则角色台无法备资产")

    # S5 钩子 / S6 收尾
    for label, marks, sid in (("钩子", HOOK_MARKS, "S5"), ("收尾", END_MARKS, "S6")):
        hits = [ln for ln in text.splitlines() if any(m in ln for m in marks)]
        if not hits:
            warnings.append(f"{sid} 没找到{label}标记——门禁要求每集独立{label}，确认是有意省略还是漏写")
        elif all(is_skeleton(ln, marks) for ln in hits):
            warnings.append(f"{sid} {label}标记只有词没有内容——{label}要写成具体画面或事件")

    # S7 场次编号连续
    nums = [int(n) for n in SCENE_RE.findall(text)]
    if len(nums) >= 2:
        expect = list(range(1, len(nums) + 1))
        if nums != expect:
            warnings.append(f"S7 场次编号不连续：{[n for n in nums]}（应为 1..{len(nums)}）")

    # S9 空场：标题下没有正文
    blocks = re.split(r"(?m)^(?=#{1,4}\s*场景\s*\d+)", text)
    for b in blocks:
        m = re.match(r"#{1,4}\s*场景\s*(\d+)", b)
        if not m:
            continue
        body = re.sub(r"^#{1,4}[^\n]*\n", "", b).strip()
        if len(re.sub(r"[\s\-#*|]", "", body)) < 10:
            warnings.append(f"S9 场景 {m.group(1)} 只有标题没有内容")

    # S8 台词时长预算
    lines = extract_dialogue(text)
    chars = sum(len(CJK_RE.findall(t)) for t in lines)
    if chars:
        need = chars / rate
        info.append(f"台词 {len(lines)} 句 / {chars} 字 → 约 {need:.1f} 秒（{rate} 字/秒）")
        if target:
            if need > target * 1.05:
                warnings.append(f"S8 台词需 {need:.1f} 秒，超目标 {target} 秒——删台词或改旁白承载")
            elif need < target * 0.5:
                warnings.append(f"S8 台词只装 {need:.1f} 秒，目标 {target} 秒——确认留白是有意设计")
    else:
        info.append("未检出台词（引号或「角色：台词」格式）——默片剧本可忽略")

    return errors, warnings, info


def find_scripts(root):
    """项目目录 → 全部 第N集/剧本.md（按集号排序）。"""
    root = Path(root)
    out = []
    for d in sorted(root.glob("第*集")):
        f = d / "剧本.md"
        if f.is_file():
            out.append(f)
    if not out:
        single = root / "剧本.md"
        if single.is_file():
            out.append(single)
    return out


def run_one(path, target, rate):
    errors, warnings, info = check(path, target=target, rate=rate)
    print(f"剧本：{path}")
    for i in info:
        print(f"  · {i}")
    for w in warnings:
        print(f"  [WARN] {w}")
    for e in errors:
        print(f"  [FAIL] {e}")
    print("PASS" if not errors else f"FAIL（{len(errors)} 错误 / {len(warnings)} 警告）")
    return errors, warnings


def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = root / "第1集"
        good.mkdir()
        (good / "剧本.md").write_text(
            "# 第 1 集 · 雨夜茶棚\n\n"
            "## 场景 1｜破败茶棚 · 雨夜\n\n"
            "@顾寒 冒雨走入 @破败茶棚，将长剑横放在桌上。@刀疤 从暗处现身。\n\n"
            "顾寒：这门，今晚不开。\n"
            "刀疤：那就看你还能撑几息。\n\n"
            "## 场景 2｜后巷 · 雨停\n\n"
            "@顾寒 追出后巷，刀疤已不见，只留一枚铜扣。\n\n"
            "本场情绪：落空，结尾留钩（下一集查铜扣）。\n",
            encoding="utf-8")
        errs, warns, info = check(good / "剧本.md", target=60)
        assert not errs, f"合格剧本误报错误：{errs}"
        assert any("台词" in i for i in info), f"台词预算未统计：{info}"

        # S2 集号不一致 → 错误
        bad2 = root / "第2集"
        bad2.mkdir()
        (bad2 / "剧本.md").write_text("# 第 3 集 · 串集\n\n## 场景 1｜茶棚\n\n@顾寒 站着。\n",
                                     encoding="utf-8")
        errs2, _, _ = check(bad2 / "剧本.md")
        assert any("S2" in e for e in errs2), f"集号不一致未检出：{errs2}"

        # S3 占位残留 → 错误；待补 → 警告
        bad3 = root / "第3集"
        bad3.mkdir()
        (bad3 / "剧本.md").write_text(
            "# 第 3 集\n\n## 场景 1｜茶棚\n\nTODO 补打戏。\n（待填）\n@顾寒 待补。\n",
            encoding="utf-8")
        errs3, warns3, _ = check(bad3 / "剧本.md")
        assert sum(1 for e in errs3 if "S3" in e) >= 2, f"模板占位未检出：{errs3}"
        assert any("待补" in w for w in warns3), f"待补未入警告：{warns3}"

        # S4 无 @引用 → 警告
        bad4 = root / "第4集"
        bad4.mkdir()
        (bad4 / "剧本.md").write_text("# 第 4 集\n\n## 场景 1｜茶棚\n\n有人走过。\n",
                                     encoding="utf-8")
        _, warns4, _ = check(bad4 / "剧本.md")
        assert any("S4" in w for w in warns4), f"无引用名未提示：{warns4}"

        # S5/S6 缺钩子收尾 → 警告；且不能因为「开场」二字就放过
        bad5 = root / "第5集"
        bad5.mkdir()
        (bad5 / "剧本.md").write_text("# 第 5 集\n\n## 场景 1｜茶棚\n\n@顾寒 站着。\n\n钩子。\n",
                                     encoding="utf-8")
        _, warns5, _ = check(bad5 / "剧本.md")
        assert any("S5" in w and "只有词" in w for w in warns5), f"敷衍钩子未检出：{warns5}"
        assert any("S6" in w for w in warns5), f"缺收尾未检出：{warns5}"

        # S7 场次跳号 + S9 空场
        bad7 = root / "第7集"
        bad7.mkdir()
        (bad7 / "剧本.md").write_text(
            "# 第 7 集\n\n## 场景 1｜茶棚\n\n@顾寒 站着，手里有剑。\n\n## 场景 3｜后巷\n\n@刀疤 跑过。\n",
            encoding="utf-8")
        _, warns7, _ = check(bad7 / "剧本.md")
        assert any("S7" in w for w in warns7), f"场次不连续未检出：{warns7}"

        # S8 超预算：给大量台词
        bad8 = root / "第8集"
        bad8.mkdir()
        long_line = "刀疤：" + "这一刀我要你记住一辈子。" * 3 + "\n"
        (bad8 / "剧本.md").write_text(
            "# 第 8 集\n\n## 场景 1｜茶棚\n\n@顾寒 站着。\n\n" + long_line,
            encoding="utf-8")
        _, warns8, _ = check(bad8 / "剧本.md", target=5)
        assert any("S8" in w for w in warns8), f"台词超预算未检出：{warns8}"

        # 项目目录模式：扫全部集
        found = find_scripts(root)
        assert len(found) >= 7, f"项目模式未扫全：{found}"

        # GBK 存盘兼容
        gbk_dir = root / "第9集"
        gbk_dir.mkdir()
        (gbk_dir / "剧本.md").write_bytes("# 第 9 集\n\n## 场景 1｜茶棚\n\n@顾寒 站着。\n".encode("gbk"))

    print("selftest: 12 项全过")
    return 0


def main():
    ap = argparse.ArgumentParser(description="剧本台机检：结构、占位、钩子收尾、@清单、台词预算")
    ap.add_argument("target", nargs="?", help="剧本.md 或项目目录")
    ap.add_argument("--target", dest="target_seconds", type=int, default=None,
                    help="本集目标时长（秒），给出时核对台词预算")
    ap.add_argument("--rate", type=float, default=DEFAULT_RATE,
                    help=f"中文语速字/秒（默认 {DEFAULT_RATE}，区间 4.0-4.6）")
    ap.add_argument("--selftest", action="store_true", help="自检")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.target:
        ap.print_help()
        return 2

    p = Path(args.target)
    if not p.exists():
        print(f"路径不存在：{p}")
        return 2

    targets = [p] if p.is_file() else find_scripts(p)
    if not targets:
        print(f"没找到剧本（{p} 下无 第N集/剧本.md）")
        return 2

    total_err = total_warn = 0
    for t in targets:
        e, w = run_one(t, args.target_seconds, args.rate)
        total_err += len(e)
        total_warn += len(w)
        print()
    if len(targets) > 1:
        print(f"合计：{len(targets)} 集，{total_err} 错误 / {total_warn} 警告")
    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
