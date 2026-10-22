#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词词层机检（只读）。

与 check_script.py 分工：
  check_script.py  查结构——必备句是否齐全、@图编号是否连续、长度是否超限。
  本工具          查用词——空词、运镜歧义、一镜多运镜、缺步态锁、缺完成态、负面约束过量。

检查项分两级：
  FAIL  明确违反项目写法（空词、运镜歧义、走秀镜缺步态锁）
  WARN  建议项（一镜多运镜、缺完成态、负面约束过量、走秀线出现手持/呼吸感）

用法：
  python tools/lint_prompt.py --script "源稿/xx分镜提示词脚本vN.md"
  python tools/lint_prompt.py --latest
  python tools/lint_prompt.py --text "某条提示词.txt"
  python tools/lint_prompt.py --text "某条提示词.txt" --line walk  # 按走秀线检查
  python tools/lint_prompt.py --selftest

退出码：0 = 无 FAIL；1 = 有 FAIL；2 = 文件或格式错误。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 空词：写了不改变画面，只稀释有效信息。命中即 FAIL。
EMPTY_WORDS = {
    "cinematic": "电影感，应写镜头、景别与光源",
    "masterpiece": "大师作品，无画面指涉",
    "8k": "分辨率是渲染设置，不是提示词",
    "4k": "分辨率是渲染设置，不是提示词",
    "hyper-realistic": "超写实，应写材质与光线行为",
    "ultra-detailed": "极致细节，应写要看见的那处细节",
    "award-winning": "获奖，属于元数据词",
    "stunning": "惊艳，无画面指涉",
    "epic": "史诗，应写尺度参照物",
    "beautiful": "美丽，应写具体视觉",
    "电影感": "应写镜头、景别与光源",
    "大片感": "应写镜头、景别与光源",
    "高级感": "应写材质、光线与构图",
    "极致画质": "分辨率与画质由平台参数决定",
    "超高清": "分辨率是渲染设置，不是提示词",
    "壁纸级": "无画面指涉",
    "震撼": "应写尺度参照物",
    "完美无瑕": "应写具体质感，真实感来自可解释的细节",
    "大师级": "无画面指涉",
}

# 走秀镜必备的步态物理锁：至少命中一个。
GAIT_WORDS = ("交替", "一只脚", "脚跟先", "左右脚")
# 出现这些词说明是在写走秀行进，需要步态锁。
WALK_TRIGGERS = ("走向台前", "行进", "走秀", "台步", "迈步")

# 完成态：动作结束时有可收敛的末状态。
END_WORDS = ("停稳", "站定", "站稳", "归于静止", "静止", "结束", "收尾", "定格")
TURN_TRIGGERS = ("转身", "返程", "回身")

# 运镜类别。类别数过多说明一镜承担了多个运镜，模型可能混成一个。
CAMERA_CLASSES = {
    "推": ("推近", "推镜", "推进", "前推"),
    "拉": ("拉远", "后拉", "拉镜", "后退"),
    "摇": ("摇镜", "横摇", "纵摇", "摇拍"),
    "移": ("横移", "移镜", "平移"),
    "升降": ("升起", "升高", "降下", "下降"),
    "环绕": ("环绕", "围绕", "环移"),
    "变焦": ("变焦", "推焦", "拉焦"),
    "跟随": ("跟随", "跟拍", "跟踪"),
}

NEGATIVE_MARKERS = (
    "不出现",
    "不要",
    "禁止",
    "不得",
    "不偏色",
    "不模糊",
    "不闪烁",
    "不跳帧",
    "不变形",
    "不改变",
    "不放大",
    "不染",
)

LOOK_RE = re.compile(r"^\*\*LOOK\s*(\d{1,2})\b")
OPEN_RE = re.compile(r"^\*\*镜\s*0\s*[·・]?\s*开场")


class Prompt:
    def __init__(self, label: str, text: str):
        self.label = label
        self.text = text


def extract_from_script(text: str) -> list[Prompt]:
    """按 LOOK 标题与开场标题切分，取每条中最长的正文段（>=200 字符）。"""
    lines = text.splitlines()
    prompts: list[Prompt] = []
    label = ""
    buf: list[str] = []

    def flush() -> None:
        nonlocal label, buf
        if not label:
            return
        body = [s.strip() for s in buf if len(s.strip()) >= 200]
        if body:
            prompts.append(Prompt(label, max(body, key=len)))
        label, buf = "", []

    active = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("## "):
            if line.startswith("## 2") or line.startswith("## 3"):
                active = True
                continue
            if line.startswith("## 4") or line.startswith("## 5"):
                break
            active = False
            continue
        if not active:
            continue
        m = LOOK_RE.match(line)
        if m:
            flush()
            label = f"LOOK {int(m.group(1)):02d}"
            continue
        if OPEN_RE.match(line):
            flush()
            label = "开场"
            continue
        if label:
            buf.append(line)
    flush()
    return prompts


def extract_from_text(text: str) -> list[Prompt]:
    """按空行分段，取 >=60 字符的段。单条提示词文件通常只有一段。"""
    chunks = [c.strip() for c in re.split(r"\n\s*\n", text) if len(c.strip()) >= 60]
    if not chunks:
        chunks = [text.strip()] if text.strip() else []
    return [Prompt(f"段 {i + 1}", c) for i, c in enumerate(chunks)]


def check(prompt: Prompt, walk: bool) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []
    text = prompt.text
    low = text.lower()

    for word, why in EMPTY_WORDS.items():
        if word.isascii():
            if re.search(rf"\b{re.escape(word)}\b", low):
                fails.append(f"{prompt.label}: 空词「{word}」，{why}")
        elif word in text:
            fails.append(f"{prompt.label}: 空词「{word}」，{why}")

    if "推近" in text and not any(
        t in text for t in ("推镜", "变焦", "焦距", "向前推近", "向前推进", "机位前移")
    ):
        fails.append(f"{prompt.label}: 「推近」未说明是机位前进还是变焦，模型会随机选一种")
    if "摇镜头" in text and not any(t in text for t in ("横摇", "纵摇")):
        fails.append(f"{prompt.label}: 「摇镜头」未写轴向，应写横摇或纵摇")
    if "长镜头" in text and "长焦" not in text:
        warns.append(f"{prompt.label}: 「长镜头」确认指长时镜头，长焦应写「长焦镜头」")

    hits = [k for k, words in CAMERA_CLASSES.items() if any(w in text for w in words)]
    if len(hits) >= 4 and "开场" not in prompt.label:
        warns.append(f"{prompt.label}: 一镜命中 {len(hits)} 类运镜（{'/'.join(hits)}），建议收敛到一到两类")

    is_walk = walk or any(t in text for t in WALK_TRIGGERS)
    if is_walk and not any(g in text for g in GAIT_WORDS):
        fails.append(
            f"{prompt.label}: 走秀行进缺步态物理锁（写「脚跟先落地、左右脚严格交替、始终有一只脚着地」）"
        )

    if any(t in text for t in TURN_TRIGGERS) and not any(e in text for e in END_WORDS):
        warns.append(f"{prompt.label}: 有转身或返程但缺完成态（写「转身站稳后再起步」「镜头末段减速停稳」）")

    neg = sum(text.count(m) for m in NEGATIVE_MARKERS)
    if neg >= 12:
        warns.append(f"{prompt.label}: 负面约束 {neg} 处，偏多会稀释；按风险保留，删与本镜无关的项")

    if is_walk and any(t in text for t in ("手持", "呼吸感", "轻微抖动")):
        warns.append(f"{prompt.label}: 走秀线出现手持或呼吸感，会削弱换机位掩护，确认是否必要")

    return fails, warns


def find_latest(root: Path, pattern: str) -> Path | None:
    src = root / "源稿"
    base = src if src.is_dir() else root
    best: tuple[tuple[int, float], Path] | None = None
    for p in base.glob(pattern):
        m = re.search(r"v(\d+)", p.stem)
        if not m:
            continue
        key = (int(m.group(1)), p.stat().st_mtime)
        if best is None or key > best[0]:
            best = (key, p)
    return best[1] if best else None


def selftest() -> int:
    """内置样例验证判别力，不依赖项目文件。"""
    cases = [
        (
            "empty_word",
            "镜头缓慢推近至近景，电影感，8K，画面明亮。",
            "空词",
        ),
        (
            "gait_missing",
            "模特沿中线走向台前，行进过程连续可见。随后站定，镜头推镜至近景，最后停稳。",
            "步态物理锁",
        ),
        (
            "camera_overload",
            "镜头推镜向前，随后横移，再摇镜，最后升起并环绕。模特站定，画面停稳。",
            "类运镜",
        ),
        (
            "clean",
            "模特沿中线走向台前，脚跟先落地、左右脚严格交替、始终有一只脚着地。"
            "镜头推镜缓缓向前，随后随她转身向后退，景别拉远至中全景，末段减速停稳。",
            "",
        ),
    ]
    ok = True
    for name, text, want in cases:
        fails, warns = check(Prompt("样例", text), walk=True)
        all_items = fails + warns
        if want:
            hit = any(want in i for i in all_items)
            print(f"[{'OK' if hit else 'FAIL'}] selftest {name}：期望命中「{want}」")
            ok = ok and hit
        else:
            clean = not fails
            print(f"[{'OK' if clean else 'FAIL'}] selftest {name}：期望无 FAIL")
            ok = ok and clean
    print("selftest：PASS" if ok else "selftest：FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="提示词词层机检（只读）")
    ap.add_argument("--script", help="分镜脚本 md 路径")
    ap.add_argument("--text", help="单条提示词 txt/md 路径")
    ap.add_argument("--latest", action="store_true", help="自动取 源稿/ 下版本号最大的分镜脚本")
    ap.add_argument("--glob", default="*分镜提示词脚本v*.md", help="--latest 时使用的文件名模式")
    ap.add_argument("--line", choices=["walk", "general"], default="walk", help="检查口径，默认走秀线")
    ap.add_argument("--selftest", action="store_true", help="跑内置样例验证判别力")
    ap.add_argument("--quiet", action="store_true", help="只输出问题与结论")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.latest:
        path = find_latest(Path(__file__).resolve().parent.parent, args.glob)
        if path is None:
            print("[错误] 未找到匹配的分镜提示词脚本，可用 --glob 指定模式")
            return 2
        via_script = True
    elif args.script:
        path = Path(args.script)
        via_script = True
    elif args.text:
        path = Path(args.text)
        via_script = False
    else:
        print("[错误] 需要 --script、--latest 或 --text")
        return 2

    if not path.is_file():
        print(f"[错误] 文件不存在：{path}")
        return 2

    text = path.read_text(encoding="utf-8", errors="replace")
    prompts = extract_from_script(text) if via_script else extract_from_text(text)
    if not prompts:
        print("[错误] 未解析到提示词。分镜脚本请确认含「## 3 LOOK」与 **LOOK NN** 标题。")
        return 2

    fails: list[str] = []
    warns: list[str] = []
    walk = args.line == "walk"
    for p in prompts:
        f, w = check(p, walk)
        fails.extend(f)
        warns.extend(w)

    if not args.quiet:
        print("== 提示词词层机检 ==")
        print(f"文件：{path}")
        print(f"条数：{len(prompts)}　口径：{'走秀' if walk else '通用'}")
        print()

    for item in fails:
        print(f"[FAIL] {item}")
    for item in warns:
        print(f"[WARN] {item}")

    print()
    if fails:
        print(f"结果：FAIL（{len(fails)} 项必修，{len(warns)} 项建议）")
        return 1
    print(f"结果：PASS（{len(warns)} 项建议）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
