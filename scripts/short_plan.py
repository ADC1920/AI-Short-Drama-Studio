#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""短视频脚本机检：口播时长预算、钩子位置、分镜节奏、发布包完整性。

短视频（1 分钟内单条）与短剧的差别不在写法，在**预算**：总时长是硬上限，
口播字数、镜头数、钩子出现位置都必须由它反推。这个脚本把那条反推做成可跑的数。

用法:
    python short_plan.py --script 脚本.md [--target 60] [--json]
    python short_plan.py --target 60                  # 只算预算参考值
    python short_plan.py --selftest

退出码: 0=预算内可交付, 1=超预算或有硬伤, 2=用法错误

口径说明（来源见 docs/ecosystem-survey-2026-10-short-video.md）:
  中文口播语速取 4.0-4.6 字/秒（多来源交集）。英文旁白的 1.5-2 字/秒
  不适用于中文，跨语言照抄会把 60 秒写成一半预算。
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 中文口播语速区间（字/秒）。下限偏保守（含停顿），上限偏激进（快节奏）。
RATE_MIN, RATE_MAX = 4.0, 4.6
# 单镜头时长下限：低于此值模型来不及完成切镜（多来源一致口径）
SHOT_MIN = 1.5
# 钩子必须完成的时间点：前 N 秒内要出现抓停元素
HOOK_SECONDS = 3.0
# 三档节奏：每镜时长区间（秒）
PACING = {
    "hook": (0.8, 2.0),     # 抖音/TikTok/信息流：高密度，每秒一个信息点
    "tutorial": (2.0, 5.0),  # 科普/教程/演示
    "documentary": (3.0, 8.0),  # vlog/品牌片/慢叙事
}
CJK = re.compile(r"[\u4e00-\u9fff]")
# 播出文字里的标记不计入口播字数
MARKUP_RE = re.compile(r"[#*`>|~\[\]()（）【】「」《》]")
# 分镜表行：| 0-3s | ... 或 0-3s：...
SHOT_LINE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-–~至]\s*(\d+(?:\.\d+)?)\s*(?:s|秒)")
HEAD_RE = re.compile(r"^#{1,6}\s*(.+)$", re.M)


def speaking_chars(text):
    """口播字数：中文字符 + 英文单词按 1.5 字计（英文一个词约等于 1.5 个汉字时长）。"""
    t = MARKUP_RE.sub(" ", text)
    cjk = len(CJK.findall(t))
    latin = len(re.findall(r"[A-Za-z]+", t))
    return cjk + int(latin * 1.5)


def budget(target):
    """按目标时长反推口播字数与镜头数区间。"""
    lo = int(target * RATE_MIN)
    hi = int(target * RATE_MAX)
    shots = {}
    for k, (a, b) in PACING.items():
        shots[k] = (max(1, int(target / b)), max(1, int(target / a)))
    return {"target": target, "chars": (lo, hi), "shots": shots}


def parse_segments(text):
    """从分镜表里抽出 (起, 止) 时间段，按出现顺序。"""
    segs = []
    for ln in text.splitlines():
        for m in SHOT_LINE_RE.finditer(ln):
            a, b = float(m.group(1)), float(m.group(2))
            if b > a:
                segs.append((a, b))
    return segs


def section_text(text, *keys):
    """取标题含任一关键词的小节正文（到下一个同级或更高级标题为止）。"""
    lines = text.splitlines()
    out, level, capturing = [], None, False
    for ln in lines:
        m = HEAD_RE.match(ln)
        if m:
            lv = len(ln) - len(ln.lstrip("#"))
            if capturing and lv <= level:
                break
            if any(k in m.group(1) for k in keys):
                capturing, level = True, lv
                continue
        if capturing:
            out.append(ln)
    return "\n".join(out)


def analyze(text, target=None):
    """返回检查结果。target 为 None 时只做内容检查不做预算比对。"""
    issues, notes = [], []
    segs = parse_segments(text)

    if segs:
        total = max(b for _, b in segs)
        gaps = []
        prev_end = 0.0
        for a, b in segs:
            if abs(a - prev_end) > 0.05 and prev_end > 0:
                gaps.append((prev_end, a))
            prev_end = b
        shortest = min(b - a for a, b in segs)
        notes.append(f"分镜 {len(segs)} 段，时间轴到 {total:g}s，最短单镜 {shortest:g}s")
        if shortest < SHOT_MIN:
            issues.append(f"单镜最短 {shortest:g}s < {SHOT_MIN}s：模型来不及完成切镜，两镜会糊成一团")
        if gaps:
            desc = "、".join(f"{a:g}-{b:g}s" for a, b in gaps[:3])
            issues.append(f"时间轴有 {len(gaps)} 处断档（{desc}）：要么补齐，要么本来就是留白需注明")
        if target and total > target + 0.5:
            issues.append(f"分镜总时长 {total:g}s 超出目标 {target:g}s")
        if target and total < target - 0.5:
            notes.append(f"分镜总时长 {total:g}s 短于目标 {target:g}s（允许，宁短不长）")
        # 钩子必须在前 HOOK_SECONDS 内出现
        first = segs[0]
        if first[0] > 0.05:
            issues.append(f"分镜从 {first[0]:g}s 才开始：前 {HOOK_SECONDS:g}s 不能空着")
    else:
        notes.append("未识别到分镜时间轴（写成 | 0-3s | ... | 形式才能检查节奏）")

    spoken = section_text(text, "口播", "台词", "旁白")
    chars = speaking_chars(spoken) if spoken.strip() else 0
    if chars:
        if target:
            rate = chars / target
            lo, hi = RATE_MIN, RATE_MAX
            notes.append(f"口播 {chars} 字 / 目标 {target:g}s = {rate:.1f} 字每秒")
            b = budget(target)
            if chars > b["chars"][1]:
                issues.append(f"口播 {chars} 字超出 {target:g}s 上限 {b['chars'][1]} 字"
                              f"（{rate:.1f} 字/秒，念不完会赶）")
            elif chars < b["chars"][0]:
                notes.append(f"口播 {chars} 字低于 {target:g}s 下限 {b['chars'][0]} 字"
                             f"（{rate:.1f} 字/秒，偏松，可加信息或缩短时长）")
        else:
            notes.append(f"口播 {chars} 字（未给目标时长，未做比对）")
    else:
        notes.append("未找到口播/台词小节")

    # 钩子：前 HOOK_SECONDS 对应的分镜里是否出现文字标记
    if segs:
        hook_part = [s for s in segs if s[0] < HOOK_SECONDS]
        if not hook_part:
            issues.append(f"前 {HOOK_SECONDS:g}s 没有镜头，无法建立钩子")
    hook_sec = section_text(text, "钩子", "标题")
    if not hook_sec.strip():
        issues.append("缺少「钩子」小节：前 3 秒抓停的那句话必须单独写出来")
    elif "随便" in hook_sec or "待定" in hook_sec:
        issues.append("钩子写成「随便/待定」：这是未定稿，必须给出具体句子")

    # 发布包：单条短视频的交付不止成片
    for key, label in (("封面", "封面文案"), ("话题", "话题标签"), ("评论", "评论区引导")):
        if key not in text:
            notes.append(f"未见{label}：单条短视频建议交付时补齐（发布台门禁）")

    return {"issues": issues, "notes": notes,
            "segments": len(segs), "chars": chars}


def selftest():
    # 1) 预算换算
    b = budget(60)
    assert b["chars"] == (240, 276), b["chars"]
    assert b["shots"]["hook"][0] >= 7, b["shots"]

    # 2) 合规样例：60s、口播 260 字、9 段无断档
    good = """# 测试脚本

## 钩子
她用三个月工资买了台二手相机，开箱那刻手在抖。

## 口播
""" + "字" * 260 + """

## 分镜
| 时间 | 画面 | 口播 |
|---|---|---|
| 0-3s | 特写手指抚过机身 | 她用三个月工资 |
| 3-8s | 拆封纸箱 | 买了台二手相机 |
| 8-15s | 镜头对准窗外 | 开箱那刻手在抖 |
| 15-25s | 第一次按下快门 | 第一张照片是糊的 |
| 25-35s | 回看照片 | 她说这张最好看 |
| 35-45s | 换镜头特写 | 后来她拍了三年 |
| 45-55s | 相册翻页 | 一共四万张 |
| 55-60s | 她把相机递给女儿 | 现在轮到你 |

## 封面文案
三个月工资，一台二手相机

## 话题标签
#摄影 #二手相机

## 评论区引导
你的第一台相机是什么？
"""
    r = analyze(good, 60)
    assert not r["issues"], r["issues"]
    assert r["segments"] == 8, r["segments"]

    # 3) 超预算口播
    too_long = good.replace("字" * 260, "字" * 500)
    r = analyze(too_long, 60)
    assert any("超出" in i for i in r["issues"]), r["issues"]

    # 4) 单镜过短
    short_shot = good.replace("| 0-3s | 特写手指抚过机身 | 她用三个月工资 |",
                              "| 2.0-3.0s | 特写手指抚过机身 | 她用三个月工资 |")
    r = analyze(short_shot, 60)
    assert any("单镜最短" in i for i in r["issues"]), r["issues"]

    # 5) 缺钩子小节
    no_hook = good.replace("## 钩子\n她用三个月工资买了台二手相机，开箱那刻手在抖。\n", "")
    r = analyze(no_hook, 60)
    assert any("钩子" in i for i in r["issues"]), r["issues"]

    # 6) 钩子敷衍
    lazy = good.replace("她用三个月工资买了台二手相机，开箱那刻手在抖。", "随便")
    r = analyze(lazy, 60)
    assert any("随便" in i for i in r["issues"]), r["issues"]

    # 7) 时间轴断档
    gapped = good.replace("| 8-15s | 镜头对准窗外 | 开箱那刻手在抖 |",
                          "| 10-15s | 镜头对准窗外 | 开箱那刻手在抖 |")
    r = analyze(gapped, 60)
    assert any("断档" in i for i in r["issues"]), r["issues"]

    # 8) 英文旁白字数换算
    assert speaking_chars("abc def") == 3, speaking_chars("abc def")

    print("short_plan selftest: OK（预算换算 / 合规样例 / 超预算 / 单镜过短 / "
          "缺钩子 / 钩子敷衍 / 时间轴断档 / 英文换算）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="短视频脚本机检：时长预算、钩子、分镜节奏")
    ap.add_argument("--script", help="脚本 md 路径")
    ap.add_argument("--target", type=float, help="目标时长（秒），默认读 studio.json")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    target = args.target
    if args.script:
        p = Path(args.script)
        if not p.is_file():
            print(f"文件不存在：{p}")
            return 2
        if target is None:
            cfg = p.parent / "studio.json"
            if cfg.is_file():
                try:
                    target = json.loads(cfg.read_text(encoding="utf-8")).get("target_seconds")
                except (json.JSONDecodeError, OSError):
                    target = None
        text = p.read_text(encoding="utf-8", errors="replace")
        result = analyze(text, target)
        result["target"] = target
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            b = budget(target) if target else None
            if b:
                print(f"目标 {target:g}s · 口播建议 {b['chars'][0]}-{b['chars'][1]} 字 · "
                      f"镜头 hook型 {b['shots']['hook'][0]}-{b['shots']['hook'][1]} / "
                      f"教程型 {b['shots']['tutorial'][0]}-{b['shots']['tutorial'][1]} 镜")
            for n in result["notes"]:
                print(f"  参考：{n}")
            if result["issues"]:
                for i in result["issues"]:
                    print(f"  错误：{i}")
                print(f"FAIL（{len(result['issues'])} 项）")
                return 1
            print("PASS（预算与节奏无硬伤）")
        return 1 if result["issues"] else 0

    if target is None:
        print("需要 --script 或 --target")
        return 2
    b = budget(target)
    print(f"目标 {target:g}s：口播 {b['chars'][0]}-{b['chars'][1]} 字 "
          f"（{RATE_MIN}-{RATE_MAX} 字/秒）")
    for k, (lo, hi) in b["shots"].items():
        print(f"  {k:<12} {lo}-{hi} 镜")
    return 0


if __name__ == "__main__":
    sys.exit(main())
