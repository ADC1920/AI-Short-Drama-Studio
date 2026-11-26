#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""短剧工作室总控（ai-short-drama-studio 技能 v3.0.0）。

十段弹性路由：01 概念 → 02 角色 → 03 世界观 → 04 分场 → 05 剧本融合
→ 06 资产 → 07 表演 → 08 分镜提示词 → 09 出片 → 10 后期发布。
每段可单独进入（单阶段模式），也可顺序推进（全流程模式）；上游改动
只把下游标为可能过期，不自动重写。

用法:
    python studio.py init <项目目录> [--title 标题] [--episodes N] [--aspect 9:16] [--model seedance-2.5]
    python studio.py status <项目目录> [--json] [--impact @素材名]
    python studio.py check <项目目录> [--json]
    python studio.py board <项目目录> [--out 看板.html]
    python studio.py selftest

项目结构（新七目录；旧多集目录仍可读）:
    <项目>/
      studio.json              项目配置（仅手填项，进度实时扫盘）
      00_project/              brief.md / project-status.md / routing.md / history/
      00_inbox/                用户上传资料登记
      01_story/                synopsis.md / characters.md / worldbuilding.md / 第N集/treatment.md
      02_script/第N集/剧本.md
      03_assets/               角色/场景/道具参考图，文件名 = @引用名（根级全剧共用）
      04_performance/第N集/    acting-vNN.md
      05_shots/第N集/          sb.json / 定稿图 / _manifest.json / 视频段/ / 成片/
      06_prompts/第N集/        cinedance-vNN.md
      场景板/                  场景单数据与图

布局兼容（ponytail: 老项目不迁移，扫盘时自动判别；当最后一个 v2 项目迁走后
可删 detect_layout 的 v2 分支）:
    <项目>/第N集/{剧本.md,分镜/,成片/} + 素材/ + 场景板/

退出码: 0=正常/检查通过, 1=检查有失败, 2=用法/路径错误
"""
import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO_NAME = "studio.json"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
SB_EXTS = {".json"}
VIDEO_EXTS = {".mp4", ".mov", ".webm"}
EP_RE = re.compile(r"^第(\d+)集$")
CONFIG_DEFAULTS = {
    "schema": 3,
    "form": "drama",
    "title": "",
    "aspect": "9:16",
    "model": "seedance-2.5",
    "episodes": 1,
    "scene_plate": None,
    "voices": {},
    "notes": "",
}
# 注意：layout 不进默认值——进了默认值会让老项目的 studio.json 被误判成 v3

FORMS = ("drama", "short")
SCRIPT_NAMES = {"drama": "剧本.md", "short": "脚本.md"}

# ---- 十段阶段表 ----
# key 是稳定标识（机读、看板着色、selftest 断言都用它）；label 是中文段名。
# 前五段是创作段（v3 新增 01-04 与 07），后五段对应 v2 的五工位。
STAGE_SEQ = (
    ("concept", "概念锚定"),
    ("characters", "角色圣经"),
    ("world", "世界观设定"),
    ("treatment", "分场大纲"),
    ("script", "剧本融合"),
    ("assets", "资产与场景板"),
    ("performance", "表演层"),
    ("storyboard", "分镜与提示词"),
    ("video", "出片与台账"),
    ("post", "后期与发布"),
)
STAGE_KEYS = tuple(k for k, _ in STAGE_SEQ)

# 短视频形态沿用同一套阶段键，只有末段与首段改名（脚本台/发布台）
STAGE_NAMES = {
    "drama": dict(STAGE_SEQ),
    "short": dict(STAGE_SEQ,
                  concept="脚本概念", script="脚本台", assets="素材台", post="发布台"),
}

# v2 五工位名（旧项目看板与话术仍用这些词）
V2_STAGE_NAMES = ("剧本台", "角色与场景台", "分镜台", "出片台", "后期台")

# 七目录布局：阶段 → 目录（相对项目根）
LAYOUT_V3 = {
    "project": "00_project",
    "inbox": "00_inbox",
    "story": "01_story",
    "script": "02_script",
    "assets": "03_assets",
    "performance": "04_performance",
    "shots": "05_shots",
    "prompts": "06_prompts",
    "plates": "场景板",
}
# v2 布局回退路径：素材目录与集目录都挂在根上
LAYOUT_V2 = {"assets": "素材", "plates": "场景板"}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def detect_layout(root: Path, cfg=None):
    """判项目布局：v3=七目录，v2=旧多集目录。

    判据顺序：studio.json 的 schema 字段（v2 项目显式落 v2）→ layout 字段
    （新项目建时写明）→ 磁盘特征（有 00_project/ 或 02_script/ 即 v3）。
    """
    cfg = cfg or {}
    if int(cfg.get("schema") or 0) <= 2:
        return "v2"
    layout = cfg.get("layout")
    if layout in ("v3", "v2"):
        return layout
    if (root / "00_project").is_dir() or (root / "02_script").is_dir():
        return "v3"
    return "v2"


def layout_paths(root: Path, cfg=None):
    """返回本项目实际使用的目录路径表（v3 七目录或 v2 回退）。"""
    if detect_layout(root, cfg) == "v3":
        return {k: root / v for k, v in LAYOUT_V3.items()}
    return {"inbox": root / "00_inbox",
            "project": root / "00_project",
            "assets": root / LAYOUT_V2["assets"],
            "plates": root / LAYOUT_V2["plates"]}


def episode_dirs(root: Path):
    out = []
    if not root.is_dir():
        return out
    for p in root.iterdir():
        m = EP_RE.match(p.name)
        if p.is_dir() and m:
            out.append((int(m.group(1)), p))
    return sorted(out)


def episode_nums(root: Path, cfg=None):
    """集号来源：v3 从 02_script/第N集 取；v2 从项目根 第N集 取。

    两处都有时取并集，避免刚迁移到一半的项目漏集。
    """
    nums = {n for n, _ in episode_dirs(root)}
    if detect_layout(root, cfg) == "v3":
        nums |= {n for n, _ in episode_dirs(root / LAYOUT_V3["script"])}
    return sorted(nums)


def unit_dirs(root: Path, cfg, num):
    """单集的全部阶段目录（v3）或同一目录（v2，各段共用）。

    v3 下每段一个目录，返回字典；v2 下所有段指向同一个 第N集/ 目录，
    下游代码只认 has-mapping，不必分支。
    """
    if detect_layout(root, cfg) == "v3":
        return {
            "story": root / LAYOUT_V3["story"] / f"第{num}集",
            "script": root / LAYOUT_V3["script"] / f"第{num}集",
            "performance": root / LAYOUT_V3["performance"] / f"第{num}集",
            "shots": root / LAYOUT_V3["shots"] / f"第{num}集",
            "prompts": root / LAYOUT_V3["prompts"] / f"第{num}集",
        }
    old = root / f"第{num}集"
    return {"story": old, "script": old, "performance": old,
            "shots": old, "prompts": old}


def units(root: Path, cfg):
    """工位推进单位：短剧=每集一个，短视频=整个项目一条。

    每个单位带齐十段用到的全部路径，下游扫盘只看这里的字段。
    """
    if (cfg.get("form") or "drama") == "short":
        if detect_layout(root, cfg) == "v3":
            sp = root / LAYOUT_V3["script"]
            return [{"label": "本片", "num": 1, "dir": sp,
                     "script": sp / SCRIPT_NAMES["short"],
                     "story": root / LAYOUT_V3["story"],
                     "performance": root / LAYOUT_V3["performance"],
                     "shots": root / LAYOUT_V3["shots"],
                     "prompts": root / LAYOUT_V3["prompts"],
                     "sbd": root / LAYOUT_V3["shots"]}]
        return [{"label": "本片", "num": 1, "dir": root,
                 "script": root / SCRIPT_NAMES["short"],
                 "story": root, "performance": root,
                 "shots": root, "prompts": root, "sbd": root}]

    out = []
    for num in episode_nums(root, cfg):
        d = unit_dirs(root, cfg, num)
        out.append({"label": f"第{num}集", "num": num, "dir": d["script"],
                    "script": d["script"] / SCRIPT_NAMES["drama"],
                    "story": d["story"], "performance": d["performance"],
                    "shots": d["shots"], "prompts": d["prompts"],
                    "sbd": shots_dir(root, cfg, d)})
    return out


def shots_dir(root: Path, cfg, d):
    """分镜文件所在目录（含 sb.json / 视频段 / 成片）。

    v3 直接用 05_shots/第N集；v2 是 第N集/分镜。显式算出来避免
    靠目录名猜布局——新旧布局的集目录名都以「第」开头，猜不准。
    """
    if detect_layout(root, cfg) == "v3":
        return d["shots"]
    return d["script"] / "分镜"


def load_config(root: Path):
    cfg = dict(CONFIG_DEFAULTS)
    f = root / STUDIO_NAME
    if f.is_file():
        try:
            cfg.update(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            print(f"警告：{STUDIO_NAME} 无法解析（{e}），按默认配置继续")
    if not cfg.get("title"):
        cfg["title"] = root.name
    return cfg


def save_config(root: Path, cfg: dict):
    f = root / STUDIO_NAME
    f.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="\n")
    return f


def script_ready(p: Path):
    if not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    body = [ln for ln in text.splitlines() if ln.strip()]
    return len(body) >= 3 and "（本集剧本：" not in text


def list_files(d: Path, exts):
    if not d.is_dir():
        return []
    return [p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in exts]


def storyboard_jsons(shots: Path):
    """分镜 JSON：v3 在 05_shots/第N集/，v2 在 第N集/分镜/。传目录即可。"""
    d = shots if shots.name != "分镜" else shots
    if not d.is_dir():
        return []
    return [p for p in d.glob("*.json") if p.name != "_manifest.json"]


def short_storyboard_root(root: Path, cfg=None):
    """短视频：分镜目录直接挂在项目根或 05_shots/，且分镜表通常写在 脚本.md 里。"""
    out = []
    dirs = [root / "分镜"]
    if detect_layout(root, cfg) == "v3":
        dirs.append(root / LAYOUT_V3["shots"])
    for d in dirs:
        if d.is_dir():
            out += [p for p in d.glob("*.json") if p.name != "_manifest.json"]
            out += [p for p in d.glob("*.md")]
    script = root / SCRIPT_NAMES["short"]
    if not script.is_file() and detect_layout(root, cfg) == "v3":
        script = root / LAYOUT_V3["script"] / SCRIPT_NAMES["short"]
    if script.is_file():
        try:
            text = script.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        # 脚本里出现时间轴分镜表，即视为分镜已产出
        if re.search(r"\|\s*\d+(?:\.\d+)?\s*[-–~至]\s*\d+", text):
            out.append(script)
    return out


def video_segments(shots: Path):
    for d in (shots / "视频段", shots / "分镜" / "视频段"):
        if d.is_dir():
            vids = list_files(d, VIDEO_EXTS)
            if vids:
                return vids
    return []


def final_videos(shots: Path):
    for d in (shots / "成片", shots / "分镜" / "成片"):
        if d.is_dir():
            vids = [p for p in d.glob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
            if vids:
                return vids
    return []


def newest(dirs):
    ts = []
    for d in dirs:
        if d.is_dir():
            ts += [p.stat().st_mtime for p in d.rglob("*") if p.is_file()]
    return max(ts) if ts else None


def oldest(dirs):
    ts = []
    for d in dirs:
        if d.is_dir():
            ts += [p.stat().st_mtime for p in d.rglob("*") if p.is_file()]
    return min(ts) if ts else None


def fmt_time(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""


def publish_files(root: Path):
    d = root / "发布"
    return [p for p in d.rglob("*") if p.is_file()] if d.is_dir() else []


def doc_ready(p: Path):
    """文档段产物判定：存在、非空、且不是模板占位。

    比剧本判定松——上游创作段没有固定小节要求，只判「写了没有」，
    内容质量仍由 review-rubric 的人工项兜。
    """
    if not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    body = [ln for ln in text.splitlines() if ln.strip()]
    if len(body) < 2:
        return False
    head = "\n".join(body[:6])
    return not re.search(r"（填|待填|TODO|XXX|占位）", head)


def stage_docs(root: Path, cfg, key):
    """上游三段（概念/角色/世界观）的产物路径；v3 在 01_story，v2 无此段。"""
    if detect_layout(root, cfg) != "v3":
        return None
    names = {"concept": "synopsis.md", "characters": "characters.md",
             "world": "worldbuilding.md"}
    return root / LAYOUT_V3["story"] / names[key]


def collect(root: Path):
    cfg = load_config(root)
    form = cfg.get("form") or "drama"
    names = STAGE_NAMES[form]
    paths = layout_paths(root, cfg)
    us = units(root, cfg)
    eps = episode_nums(root, cfg)
    cfg_episodes = int(cfg.get("episodes") or 0)
    if form == "drama" and cfg_episodes < len(eps):
        cfg["episodes"] = len(eps)

    per = []
    for u in us:
        sbd = u["sbd"]
        per.append({
            "label": u["label"],
            "num": u["num"],
            "script": script_ready(u["script"]),
            "treatment": doc_ready(u["story"] / "treatment.md"),
            # 存相对路径字符串而非 Path：--json 走 json.dumps，Path 不可序列化
            "acting": [str(p.relative_to(root)) for p in sorted(u["performance"].glob("acting*.md"))
                       if doc_ready(p)] if u["performance"].is_dir() else [],
            "prompts": [str(p.relative_to(root)) for p in sorted(u["prompts"].glob("*.md"))
                        if doc_ready(p)] if u["prompts"].is_dir() else [],
            "storyboard": [str(p.relative_to(root)) for p in (
                storyboard_jsons(sbd) if form == "drama" else short_storyboard_root(root, cfg))],
            "plates": [str(p.relative_to(root)) for p in list_files(sbd, IMAGE_EXTS)],
            "segments": len(video_segments(sbd)),
            "final": len(final_videos(sbd)),
        })

    asset_dir = paths["assets"]
    asset_files = list_files(asset_dir, IMAGE_EXTS)
    plate_dir = paths["plates"]
    plate_files = ([p for p in plate_dir.rglob("*") if p.is_file()]
                   if plate_dir.is_dir() else [])
    pub = publish_files(root)
    total = len(us) if us else 1
    stages = []

    # ---- 01-04 创作段 ----
    # 短视频形态默认不强制（单条不需要正式分场与角色圣经）；写了就算数。
    optional = form == "short"
    for key, word in (("concept", "概念锚定"), ("characters", "角色圣经")):
        f = stage_docs(root, cfg, key)
        if f is None:
            stages.append(stage(key, 0, 1, "v2 布局无此段（上游在 onlyshot-drama）",
                                names, status="skip"))
        elif doc_ready(f):
            stages.append(stage(key, 1, 1, f"{f.relative_to(root)} 已就位", names))
        elif optional:
            stages.append(stage(key, 0, 1, f"短视频形态可选（{f.relative_to(root)}）",
                                names, status="skip"))
        else:
            stages.append(stage(key, 0, 1, f"待写 {f.relative_to(root)}", names))

    fw = stage_docs(root, cfg, "world")
    if fw is None:
        stages.append(stage("world", 0, 1, "v2 布局无此段（可选）", names, status="skip"))
    elif doc_ready(fw):
        stages.append(stage("world", 1, 1, f"{fw.relative_to(root)} 已就位", names))
    else:
        # 世界观始终可选：现实题材可跳过，不阻塞下游
        stages.append(stage("world", 0, 1, "可选段（复杂世界规则才写）", names, status="skip"))

    tr_done = sum(1 for x in per if x["treatment"])
    if detect_layout(root, cfg) != "v3":
        stages.append(stage("treatment", 0, 1, "v2 布局无此段（上游在 onlyshot-drama）",
                            names, status="skip"))
    elif optional:
        stages.append(stage("treatment", tr_done, total,
                            "短视频形态可选（分场大纲）" if not tr_done
                            else f"{tr_done}/{total} 集有分场大纲", names,
                            status=None if tr_done else "skip"))
    else:
        stages.append(stage("treatment", tr_done, total,
                            f"{tr_done}/{total} 集有分场大纲" if us else "尚无集目录", names))

    # ---- 05 剧本融合（原剧本台）----
    script_done = sum(1 for x in per if x["script"])
    unit_word = "集剧本" if form == "drama" else "条脚本"
    stages.append(stage("script", script_done, total,
                        f"{script_done}/{total} {unit_word}就位"
                        if us else f"尚无 {SCRIPT_NAMES[form]}", names))

    # ---- 06 资产与场景板 ----
    if asset_files or plate_files:
        extra = f" · 场景板 {len(plate_files)} 件" if plate_files else ""
        stages.append(stage("assets", 1, 1,
                            f"素材 {len(asset_files)} 件{extra}", names))
    else:
        stages.append(stage("assets", 0, 1, f"{asset_dir.name}/ 为空", names))

    # ---- 07 表演层（可选段）----
    act_done = sum(1 for x in per if x["acting"])
    act_note = "v2 布局无此段（表演并进分镜提示词）"
    if detect_layout(root, cfg) != "v3" or optional:
        stages.append(stage("performance", act_done, total,
                            f"{act_done}/{total} 集有表演稿" if act_done else act_note,
                            names, status=None if act_done else "skip"))
    else:
        stages.append(stage("performance", act_done, total,
                            f"{act_done}/{total} 集有表演稿" if us else "尚无集目录",
                            names, status=None if act_done else "skip"))

    # ---- 08 分镜与提示词 ----
    sb_done = sum(1 for x in per if x["storyboard"])
    plate_done = sum(1 for x in per if x["plates"])
    pr_done = sum(1 for x in per if x["prompts"])
    sb_word = "分镜 JSON" if form == "drama" else "分镜表"
    detail8 = (f"{sb_done}/{total} {sb_word} · {plate_done} 份定稿图"
               if us else "尚无分镜目录")
    if pr_done:
        detail8 += f" · {pr_done} 集提示词稿"
    stages.append(stage("storyboard", sb_done, total, detail8, names))

    # ---- 09 出片与台账 ----
    seg_total = sum(x["segments"] for x in per)
    vid_done = sum(1 for x in per if x["segments"] > 0)
    if form == "short" and not seg_total:
        # 单条形态常直接把逐镜片段放 成片/；出片台与发布台用同一判据，避免两处打架
        seg_total = sum(x["final"] for x in per)
        vid_done = 1 if seg_total else 0
    stages.append(stage("video", vid_done, total,
                        f"{seg_total} 段视频 · {vid_done}/{total} 有产出"
                        if us else "尚无成片目录", names))

    # ---- 10 后期与发布 ----
    if form == "short":
        has_final = any(x["final"] > 0 for x in per)
        post_done = 1 if (has_final and pub) else 0
        if post_done:
            detail = f"成片已出 · 发布包 {len(pub)} 件"
        elif has_final:
            detail = "成片已出 · 待补 发布/ 封面文案、标签、评论引导"
        else:
            detail = "尚无成片，发布包未开始"
    else:
        post_done = sum(1 for x in per if x["final"] > 0)
        detail = (f"已出 {post_done}/{total} 集成片" if us else "尚无成片")
    stages.append(stage("post", post_done, total, detail, names))

    next_stage = pick_next(stage_list=stages)
    warnings = impact_warnings(root, us, paths)

    return {
        "project": str(root),
        "form": form,
        "layout": detect_layout(root, cfg),
        "title": cfg["title"],
        "aspect": cfg.get("aspect", ""),
        "model": cfg.get("model", ""),
        "episodes": len(eps) if form == "drama" else 1,
        "configured_episodes": cfg["episodes"],
        "publish_files": len(pub),
        "stages": stages,
        "next": next_stage,
        "warnings": warnings,
        "cost": cost_summary(root),
        "episodes_detail": per,
    }


def pick_next(stage_list):
    """推荐下一段。

    单阶段模式的前提：用户可能跳着做。若某段仍 pending 但下游已经 done，
    说明下游是用户主动跳着做的，不该把焦点强行拉回最前面那段（那会诱导
    用户从 01 重跑）。所以取「第一个未完成且下游还没开工」的段；
    全部未完成时仍从 01 起。
    """
    pending = [i for i, s in enumerate(stage_list) if s["status"] in ("pending", "active")]
    if not pending:
        return None
    for i in pending:
        later_done = any(s["status"] == "done" for s in stage_list[i + 1:])
        if not later_done:
            return stage_list[i]
    return stage_list[pending[0]]


def stage(key, done, total, detail, names, status=None):
    if total <= 0:
        total = 1
    if status is None:
        if done >= total:
            status = "done"
        elif done > 0:
            status = "active"
        else:
            status = "pending"
    return {"key": key, "name": names[key],
            "done": done, "total": total, "status": status, "detail": detail}


def impact_warnings(root: Path, us, paths=None):
    """改稿回流提示：比较上下游产物时间，只提示不阻断。

    覆盖 05→06/08→09 两条主链，以及 01/02 上游改动对下游的影响。
    """
    out = []
    # 低于此值视为异常时间戳（拷贝/解压/时钟错乱），不参与先后比较，避免报假警
    sane = 946684800.0  # 2000-01-01
    paths = paths or layout_paths(root)
    asset_new = newest([paths["assets"], paths["plates"]])
    final_old = oldest([u["sbd"] / "成片" for u in us])
    if (asset_new and final_old and asset_new > sane and final_old > sane
            and asset_new > final_old):
        out.append(f"资产最新改动 {fmt_time(asset_new)} 晚于成片 {fmt_time(final_old)}："
                   f"成片可能过期，按十段回流重做 08→09→10")
    sb_files = []
    for u in us:
        d = u["sbd"]
        sb_files += [p for p in d.glob("*")
                     if p.is_file() and p.suffix.lower() in (SB_EXTS | IMAGE_EXTS)]
    sb_new = max((p.stat().st_mtime for p in sb_files), default=None)
    seg_old = oldest([u["sbd"] / "视频段" for u in us])
    if (sb_new and seg_old and sb_new > sane and seg_old > sane
            and sb_new > seg_old):
        out.append(f"分镜最新改动 {fmt_time(sb_new)} 晚于视频段 {fmt_time(seg_old)}："
                   f"已有视频段可能过期，重做 09→10")
    # 上游创作段改动：概念/角色改了，剧本与下游可能不一致
    story = paths.get("story")
    if story and story.is_dir():
        story_new = newest([story])
        script_old = oldest([u["dir"] for u in us])
        if (story_new and script_old and story_new > sane and script_old > sane
                and story_new > script_old):
            out.append(f"上游创作段最新改动 {fmt_time(story_new)} 晚于剧本 "
                       f"{fmt_time(script_old)}：剧本及以下可能与之不一致，"
                       f"按修订模式回 05 或只重做受影响部分")
    return out


def cost_summary(root: Path):
    """读 _tasks.jsonl 的成本汇总。无台账返回 None（老项目兼容）。

    台账不是门禁，是账本：只读、只汇总，不写盘、不判失败。
    """
    sys.path.insert(0, str(HERE))
    try:
        from task_ledger import load_events, fold_state, summarize
    except ImportError:
        return None
    events, bad = load_events(root)
    if not events and not bad:
        return None
    return summarize(fold_state(events), bad)


def print_status(info):
    form_label = {"drama": "短剧", "short": "短视频"}.get(info["form"], info["form"])
    print(f"{'短剧' if info['form'] == 'drama' else '短视频'}工作室 · 《{info['title']}》")
    print(f"项目：{info['project']}")
    scope = f"{info['episodes']} 集" if info["form"] == "drama" else "单条"
    layout_note = "七目录" if info.get("layout") == "v3" else "旧多集布局"
    print(f"形态 {form_label} · 画幅 {info['aspect']} · 模型 {info['model']} · "
          f"{scope} · 布局 {layout_note}\n")
    print(f"{'段':<4}{'阶段':<16}{'进度':<10}{'状态':<8}说明")
    label = {"done": "完成", "active": "进行中", "pending": "待开始", "skip": "可跳过"}
    for i, s in enumerate(info["stages"], 1):
        prog = f"{s['done']}/{s['total']}"
        print(f"{i:<4}{s['name']:<16}{prog:<10}{label[s['status']]:<8}{s['detail']}")
    nxt = info["next"]
    print()
    print(f"当前焦点段：{nxt['name']}（{nxt['detail']}）" if nxt
          else "十段产物齐备，进入整体验收。")
    if info.get("layout") == "v3":
        print("入口：全流程从 01 起；手上已有资料就从能支持的那段进，不必补前序。")
    c = info.get("cost")
    if c:
        line = (f"成本：已花 {c['spent']:.0f} 分 · "
                f"失败重抽 {c['wasted']:.0f} 分（占 {c['waste_ratio']*100:.1f}%）")
        if c["pending"]:
            line += f" · 待回执 {c['pending']} 镜"
        print("\n" + line)
        if c["waste_ratio"] > 0.10:
            print("  警告：浪费占比超过 10% 重生预算，先查素材与提示词的系统性问题")
    if info["warnings"]:
        print("\n改稿提示：")
        for w in info["warnings"]:
            print(f"  - {w}")
    # 审查记录软提示：不阻断，只提醒有产物但没审查记录
    reviews = root_of(info) / "_reviews"
    if root_of(info).is_dir() and any(s["status"] == "done" for s in info["stages"]):
        if not reviews.is_dir() or not any(reviews.glob("*.md")):
            print("\n审查：本集尚无审查记录（按 references/review-rubric.md 逐范围勾，"
                  "写进 _reviews/）")
    # 原著索引软提示：有索引但未覆盖全部章节
    novel = load_novel_index(root_of(info))
    if novel and novel.get("unread"):
        nums = "、".join(str(x) for x in novel["unread"][:8])
        print(f"\n原著：已分析 {novel.get('read_range','')}，"
              f"尚有 {len(novel['unread'])} 章未分析（{nums}）——分批用 "
              f"novel_index.py index --chapters 补")


def root_of(info):
    return Path(info["project"])


def load_novel_index(root: Path):
    """读 _novel/index.json；无则 None。只读，不建。"""
    p = root / "_novel" / "index.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def run_check(root: Path):
    cfg = load_config(root)
    form = cfg.get("form") or "drama"
    paths = layout_paths(root, cfg)
    us = units(root, cfg)
    checks = []
    py = sys.executable

    for u in us:
        # 剧本路径给 validate_storyboard 做 C11 场景覆盖对账（同集剧本同目录）
        script_for_c11 = u["script"] if u["script"].is_file() else None
        for sb in storyboard_jsons(u["sbd"]):
            cmd = [py, str(HERE / "validate_storyboard.py"), str(sb), "--no-log", "--json"]
            if script_for_c11:
                cmd += ["--script", str(script_for_c11)]
            checks.append((f"validate_storyboard {sb.relative_to(root)}", cmd))
        # 提示词稿门禁：只在 v3 七目录下按 06_prompts/ 检查。
        # v2 的 prompts 目录指向集目录本身，会把剧本.md 当提示词稿误伤。
        # 用 general 口径——cinedance 稿不是走秀线，walk 口径的步态锁必误报。
        if detect_layout(root, cfg) == "v3" and u["prompts"].is_dir():
            for pr in sorted(u["prompts"].glob("*.md")):
                checks.append((f"lint_prompt {pr.relative_to(root)}",
                               [py, str(HERE / "lint_prompt.py"), "--text", str(pr),
                                "--line", "general", "--json"]))
    if form == "short":
        for sb in short_storyboard_root(root, cfg):
            if sb.suffix.lower() == ".json":
                checks.append((f"validate_storyboard {sb.relative_to(root)}",
                               [py, str(HERE / "validate_storyboard.py"), str(sb),
                                "--no-log", "--json"]))

    if paths["assets"].is_dir():
        checks.append(("check_refs 素材与 @引用",
                       [py, str(HERE / "check_refs.py"), str(root), "--json"]))

    # 剧本段门禁：结构、占位、@清单、台词时长预算
    if form == "drama":
        for u in us:
            f = u["script"]
            if f.is_file():
                checks.append((f"check_script {f.relative_to(root)}",
                               [py, str(HERE / "check_script.py"), str(f), "--json"]))
            else:
                checks.append((f"check_script {f.relative_to(root)}（缺 {SCRIPT_NAMES['drama']}）",
                               None))

    for u in us:
        d = u["sbd"]
        if (d / "_manifest.json").is_file():
            checks.append((f"manifest verify {d.relative_to(root)}",
                           [py, str(HERE / "manifest.py"), "verify", str(d)]))

    plate = cfg.get("scene_plate")
    if plate:
        p = root / plate
        if p.is_file():
            checks.append(("check_scene_plates 场景板",
                           [py, str(HERE / "check_scene_plates.py"), str(p)]))
        else:
            checks.append(("check_scene_plates 场景板（配置文件缺失）", None))

    # 短视频特有门禁：口播字数必须落在目标时长的可听区间
    if form == "short":
        target = cfg.get("target_seconds")
        script = us[0]["script"] if us else root / SCRIPT_NAMES["short"]
        if script.is_file():
            cmd = [py, str(HERE / "short_plan.py"), "--script", str(script)]
            if target:
                cmd += ["--target", str(target)]
            checks.append(("short_plan 口播时长预算", cmd))
        else:
            checks.append(("short_plan 口播时长预算（缺 脚本.md）", None))

    # 派生索引过期检测：_impact.json 存在但比相关产物旧 → 告警（不进失败集）
    impact_file = root / "_impact.json"
    stale_impact = None
    if impact_file.is_file():
        impact_mtime = impact_file.stat().st_mtime
        newest_src = 0.0
        for u in us:
            for p in u["sbd"].glob("*"):
                if p.is_file() and p.suffix.lower() in (SB_EXTS | IMAGE_EXTS):
                    newest_src = max(newest_src, p.stat().st_mtime)
        if newest_src > impact_mtime:
            stale_impact = ("_impact.json 已过期（分镜有更新）——"
                            f"重跑 python scripts/impact_graph.py build {root}")

    results = []
    for name, cmd in checks:
        if cmd is None:
            results.append({"name": name, "ok": False, "exit": 2, "findings": [],
                            "output": "缺少必需文件"})
            continue
        try:
            cp = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
            out = (cp.stdout or "") + (cp.stderr or "")
            results.append({"name": name, "ok": cp.returncode == 0,
                            "exit": cp.returncode,
                            "findings": _parse_child_findings(cp.stdout or ""),
                            "output": out.strip()[-1200:]})
        except subprocess.TimeoutExpired:
            results.append({"name": name, "ok": False, "exit": 124, "findings": [],
                            "output": "超时（180s）"})
        except OSError as e:
            results.append({"name": name, "ok": False, "exit": 2, "findings": [],
                            "output": str(e)})

    passed = sum(1 for r in results if r["ok"])
    return {"project": str(root), "results": results,
            "ok": all(r["ok"] for r in results) if results else True,
            "summary": {"total": len(results), "passed": passed,
                        "failed": len(results) - passed},
            "warnings": [stale_impact] if stale_impact else []}


def _parse_child_findings(stdout):
    """子脚本带 --json 时输出 {ok, findings[], summary}；解析出 findings 供 agent 直读。

    解析失败返回 []（向后兼容：老脚本或非 JSON 输出），父层仍保留 output 原文兜底。
    """
    s = (stdout or "").strip()
    if not s.startswith("{"):
        return []
    try:
        data = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return []
    got = data.get("findings")
    return got if isinstance(got, list) else []


def print_check(res):
    if not res["results"]:
        print("没有可机检的产物（先到分镜台产出分镜 JSON，或先备素材）。")
        return
    for i, r in enumerate(res["results"], 1):
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"[{i}/{len(res['results'])}] {mark}  {r['name']}（exit {r['exit']}）")
        if not r["ok"] and r["output"]:
            for ln in r["output"].splitlines()[-12:]:
                print(f"    {ln}")
    print(f"\n汇总：{'全部通过' if res['ok'] else '存在失败项，按上面输出修到 PASS'}（{len(res['results'])} 项）")
    for w in res.get("warnings") or []:
        print(f"警告：{w}")


def cmd_board(args):
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"项目目录不存在：{root}")
        return 2
    info = collect(root)
    out = Path(args.out) if args.out else root / ".studio" / "board.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_board(info), encoding="utf-8", newline="\n")
    print(f"看板已生成：{out}")
    return 0


BOARD_CSS = """
:root{--bg:#0f1115;--panel:#171a21;--line:rgba(255,255,255,.09);--txt:#e6edf3;
--dim:#9aa4b2;--faint:#6e7681;--done:#3fb950;--active:#d29922;--wait:#6e7681}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:32px 24px 48px}
h1{margin:0 0 6px;font-size:22px;font-weight:650;letter-spacing:.2px}
.meta{color:var(--dim);font-size:13px}
.meta span{margin-right:14px}
.track{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:28px 0 24px}.st{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}
.st.now{border-color:var(--active);box-shadow:0 0 0 1px rgba(210,153,34,.35)}
.st.done .dot{background:var(--done)}
.st.active .dot{background:var(--active)}
.st.pending{background:#14171d;border-color:rgba(255,255,255,.06)}
.st.pending .no{color:#5d646e}
.st.pending .nm{color:#b9c1cc}
.st.pending .prog{color:#8b949e}
.st.pending .det{color:#7d8590}
.st.pending .dot{background:var(--wait)}
.st.skip{background:#12151a;border-color:rgba(255,255,255,.04);opacity:.72}
.st.skip .dot{background:transparent;border:1px solid var(--wait)}
.st .no{color:var(--faint);font-size:11px;letter-spacing:.08em}
.st .nm{margin:4px 0 10px;font-size:14px;font-weight:600}
.st .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;
vertical-align:middle}
.st .prog{font-variant-numeric:tabular-nums;font-size:18px;font-weight:600}
.st .prog small{font-size:12px;color:var(--faint);font-weight:400}
.st .det{color:var(--dim);font-size:12px;margin-top:6px;min-height:2.4em}
.cols{display:grid;grid-template-columns:1.55fr 1fr;gap:16px}
@media(max-width:900px){.cols{grid-template-columns:1fr}.track{grid-template-columns:1fr 1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px}
.card h2{margin:0 0 12px;font-size:13px;font-weight:600;color:var(--dim);
letter-spacing:.04em;text-transform:uppercase}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--faint);font-weight:500;font-size:11px;letter-spacing:.04em}
td.num{font-variant-numeric:tabular-nums}
.y{color:var(--done)}.n{color:var(--faint)}
.warn{border-left:2px solid var(--active);padding:4px 0 4px 10px;margin:0 0 10px;
color:var(--dim);font-size:13px}
code{font:12px/1.5 Consolas,"Courier New",monospace;background:rgba(255,255,255,.06);
padding:2px 6px;border-radius:4px;color:#c9d1d9}
.next{margin-top:14px;padding-top:14px;border-top:1px solid var(--line)}
.next b{color:var(--active);font-weight:600}
.next .cmd{display:block;margin-top:8px}
.next .hint{display:block;margin-top:6px;color:var(--faint);font-size:12px}
.empty{color:var(--faint);font-size:13px}
"""


def render_board(info):
    label = {"done": "完成", "active": "进行中", "pending": "待开始", "skip": "可跳过"}
    now_key = info["next"]["key"] if info["next"] else None
    is_short = info.get("form") == "short"
    kind = "短视频工作室" if is_short else "短剧工作室"
    cells = []
    for i, s in enumerate(info["stages"], 1):
        cls = s["status"] + (" now" if s["key"] == now_key else "")
        cells.append(
            f'<div class="st {cls}"><div class="no">阶段 {i:02d}</div>'
            f'<div class="nm">{esc(s["name"])}</div>'
            f'<div><span class="dot"></span>{label[s["status"]]}</div>'
            f'<div class="prog">{s["done"]}<small>/{s["total"]}</small></div>'
            f'<div class="det">{esc(s["detail"])}</div></div>')

    if is_short:
        e = info["episodes_detail"][0] if info["episodes_detail"] else None
        if e:
            segs = e["segments"] or e["final"]
            rows = (f'<tr><td class="num">本片</td>'
                    f'<td class="{"y" if e["script"] else "n"}">{"有" if e["script"] else "—"}</td>'
                    f'<td class="num{" y" if e["storyboard"] else " n"}">{len(e["storyboard"])}</td>'
                    f'<td class="num{" y" if e["plates"] else " n"}">{len(e["plates"])}</td>'
                    f'<td class="num{" y" if segs else " n"}">{segs}</td>'
                    f'<td class="num{" y" if info.get("publish_files") else " n"}">'
                    f'{info.get("publish_files", 0)}</td></tr>')
            ep_table = ("<table><tr><th>单位</th><th>脚本</th><th>分镜表</th><th>关键帧</th>"
                        "<th>视频段</th><th>发布包</th></tr>" + rows + "</table>")
        else:
            ep_table = ('<p class="empty">还没有脚本。先跑 '
                        '<code>studio.py init --form short</code> 建项目。</p>')
        card_title = "单条明细"
    else:
        rows = []
        for e in info["episodes_detail"]:
            rows.append(
                f'<tr><td class="num">第 {e["num"]} 集</td>'
                f'<td class="{"y" if e["treatment"] else "n"}">{"有" if e["treatment"] else "—"}</td>'
                f'<td class="{"y" if e["script"] else "n"}">{"有" if e["script"] else "—"}</td>'
                f'<td class="{"y" if e["acting"] else "n"}">{"有" if e["acting"] else "—"}</td>'
                f'<td class="num{" y" if e["storyboard"] else " n"}">{len(e["storyboard"])}</td>'
                f'<td class="num{" y" if e["prompts"] else " n"}">{len(e["prompts"])}</td>'
                f'<td class="num{" y" if e["segments"] else " n"}">{e["segments"]}</td>'
                f'<td class="num{" y" if e["final"] else " n"}">{e["final"]}</td></tr>')
        ep_table = ("<table><tr><th>集</th><th>分场</th><th>剧本</th><th>表演</th>"
                    "<th>分镜</th><th>提示词</th><th>视频段</th><th>成片</th></tr>"
                    + "".join(rows) + "</table>"
                    if rows else '<p class="empty">还没有分集目录。先跑 '
                                 '<code>studio.py init</code> 建项目。</p>')
        card_title = "分集明细"

    if info["warnings"]:
        warn_html = "".join(f'<p class="warn">{esc(w)}</p>' for w in info["warnings"])
    else:
        warn_html = '<p class="empty">上游产物均早于下游，没有待回流的改稿。</p>'

    nxt = info["next"]
    if nxt:
        cmd = ("python scripts/studio.py check ." if not is_short
               else "python scripts/short_plan.py --script 02_script/脚本.md")
        next_html = (f'<div class="next">当前焦点段：<b>{esc(nxt["name"])}</b>'
                     f'<span class="hint">{esc(nxt["detail"])}</span>'
                     f'<code class="cmd">{cmd}</code>'
                     f'<span class="hint">跑门禁，全绿再往下走；手上已有资料可直接跳到能支持的那段。</span>'
                     f'</div>')
    else:
        next_html = ('<div class="next">十段产物齐备，进入整体验收：'
                     '<code class="cmd">python scripts/qa_batch.py</code></div>')

    scope = f"{info['episodes']} 集" if not is_short else "单条"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{kind} · {esc(info["title"])}</title>
<style>{BOARD_CSS}</style></head>
<body><div class="wrap">
<h1>{kind} · {esc(info["title"])}</h1>
<div class="meta"><span>画幅 {esc(str(info["aspect"]))}</span>
<span>模型 {esc(str(info["model"]))}</span>
<span>{scope}</span>
<span>生成于 {stamp}</span></div>
<div class="track">{"".join(cells)}</div>
<div class="cols">
<div class="card"><h2>{card_title}</h2>{ep_table}</div>
<div class="card"><h2>改稿回流</h2>{warn_html}{next_html}</div>
</div></div></body></html>
"""


def esc(v):
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


BRIEF_TEMPLATE = """# 项目 Brief

一句话需求：
受众：
目标平台：
目标时长：
内容类型：
视觉方向：
预算或生成次数限制：
不能出现的内容：
"""

STATUS_TEMPLATE = """# 项目状态（由路由维护）

项目名称：{title}
运行模式：待判断
目标阶段：待判断
当前状态：未开始
用户指定的权威输入：无
已确认文件：无
最近一次产出：无
可能过期的下游：无
最近一次人工确认：无
修订记录：无

## 规则

- 一次只执行一个阶段。
- 允许从任意阶段开始，也允许主动切回上游修订。
- 未经用户明确要求和确认，不改掉其他阶段已确定内容；切换和修订必须记录版本及影响范围。
- 模板不包含任何示例故事、角色、剧本或资产。
"""

ROUTING_TEMPLATE = """# 当前路由（由路由维护）

运行模式：待判断
当前阶段：待判断
当前状态：未开始
当前唯一输出：待判断
本阶段允许读取：待判断
本阶段方法来源：待判断
建议下一步：待判断

## 可选入口

- 从零开始：01 概念锚定
- 已有故事：02 角色 / 04 分场 / 05 剧本融合
- 已有最终剧本：06 资产与场景板
- 已有场景与角色：07 表演层
- 已有镜头目标与资产参考：08 分镜与提示词

## 路由原则

- 一次只执行一个阶段。
- 用户可明确切换到任意阶段，不强迫补齐无关前序。
- 未经用户明确要求和确认，不改掉其他阶段已确定内容；用户可主动回退和修订。
- 修订上游后，只把真正受影响的下游标记为可能过期。
"""


def cmd_init(args):
    root = Path(args.root).resolve()
    cfg_file = root / STUDIO_NAME
    already = cfg_file.is_file()
    form = args.form
    root.mkdir(parents=True, exist_ok=True)

    # 七目录骨架：控制文件 + 阶段目录
    for key in ("project", "inbox", "story", "script", "assets",
                "performance", "shots", "prompts", "plates"):
        (root / LAYOUT_V3[key]).mkdir(parents=True, exist_ok=True)
    (root / LAYOUT_V3["project"] / "history").mkdir(exist_ok=True)

    # 三份控制文件只在缺失时写，不覆盖用户已填内容
    controls = {
        "brief.md": BRIEF_TEMPLATE,
        "project-status.md": STATUS_TEMPLATE.format(title=args.title or root.name),
        "routing.md": ROUTING_TEMPLATE,
    }
    for name, body in controls.items():
        f = root / LAYOUT_V3["project"] / name
        if not f.exists():
            f.write_text(body, encoding="utf-8", newline="\n")

    if form == "short":
        sp = root / LAYOUT_V3["script"]
        (root / LAYOUT_V3["shots"] / "视频段").mkdir(parents=True, exist_ok=True)
        (root / LAYOUT_V3["shots"] / "成片").mkdir(parents=True, exist_ok=True)
        (root / "发布").mkdir(exist_ok=True)
        script = sp / SCRIPT_NAMES["short"]
        if not script.exists():
            script.write_text(
                "# 短视频脚本\n\n"
                "（本文件=短端口播稿+分镜表。目标时长写进 studio.json 的 target_seconds；"
                f"出场人物/场景用 @ 引用名，素材放 {LAYOUT_V3['assets']}/。）\n",
                encoding="utf-8", newline="\n")
    else:
        for ep in range(1, max(1, args.episodes) + 1):
            for key in ("story", "script", "performance", "shots", "prompts"):
                (root / LAYOUT_V3[key] / f"第{ep}集").mkdir(parents=True, exist_ok=True)
            (root / LAYOUT_V3["shots"] / f"第{ep}集" / "视频段").mkdir(exist_ok=True)
            (root / LAYOUT_V3["shots"] / f"第{ep}集" / "成片").mkdir(exist_ok=True)
            script = root / LAYOUT_V3["script"] / f"第{ep}集" / SCRIPT_NAMES["drama"]
            if not script.exists():
                script.write_text(
                    f"# 第{ep}集 剧本\n\n（本集剧本：按剧情节点切分，每集有独立的钩子与收尾。"
                    "出场角色/场景用 @ 引用名。）\n",
                    encoding="utf-8", newline="\n")

    if not already:
        cfg = dict(CONFIG_DEFAULTS)
        cfg.update({"form": form, "title": args.title or root.name,
                    "aspect": args.aspect, "model": args.model,
                    "episodes": args.episodes, "created": now(), "layout": "v3"})
        if form == "short":
            cfg["target_seconds"] = args.target
        save_config(root, cfg)

    kind = "短视频工作室" if form == "short" else "短剧工作室"
    print(f"{kind}已就绪：{root}")
    if already:
        print(f"已有 {STUDIO_NAME}，保留原配置{'' if form == 'drama' else '（形态以配置为准）'}，只补齐目录。")
    print("控制文件：00_project/{brief.md, project-status.md, routing.md} · 00_inbox/")
    if form == "short":
        print(f"阶段目录：01_story/ · {LAYOUT_V3['script']}/ · {LAYOUT_V3['assets']}/ · "
              f"{LAYOUT_V3['shots']}/ · 发布/")
        print(f"目标时长 {args.target}s；下一步：写 {LAYOUT_V3['script']}/{SCRIPT_NAMES['short']} "
              f"→ python studio.py status .")
    else:
        eps = f"第1..{max(1, args.episodes)}集"
        print(f"阶段目录：01_story/ · 02_script/ · 03_assets/ · 04_performance/ · "
              f"05_shots/ · 06_prompts/ · 场景板/")
        print(f"集级子目录：{eps}/ 摊销在 01/02/04/05/06 内")
        print("下一步：填 00_project/brief.md → 写 01_story/synopsis.md（或直接从手上已有的那段开始）"
              " → python studio.py status .")

    # 可选：初始化时顺带建原著结构索引
    novel = getattr(args, "novel", "")
    if novel:
        sys.path.insert(0, str(HERE))
        try:
            from novel_index import build_index
            src = Path(novel)
            data = build_index(src)
            out = root / "_novel" / "index.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
            n = sum(len(c.get("points") or []) for c in data["chapters"])
            print(f"原著索引：{data['chapter_count']} 章 · {data['chars']} 字 · "
                  f"情节点 {n} 个 → {out.relative_to(root)}")
        except (FileNotFoundError, ValueError, OSError, ImportError) as e:
            print(f"原著索引未建（{e}）——可稍后单独跑 novel_index.py index")
    return 0


def cmd_status(args):
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"项目目录不存在：{root}")
        return 2
    # --impact：直接答「改了 X 要重出什么」，依赖图优先于 mtime 粗判
    if getattr(args, "impact", ""):
        sys.path.insert(0, str(HERE))
        try:
            from impact_graph import load_impact, build, query, format_query
        except ImportError as e:
            print(f"影响面模块不可用：{e}")
            return 2
        data = load_impact(root)
        if data is None:
            print(f"未找到 _impact.json，先建索引：python scripts/impact_graph.py build {root}")
            return 2
        res = query(data, args.impact)
        if res is None:
            print(f"未找到引用：{args.impact}（刚改过分镜则先重跑 impact_graph build）")
            return 1
        print(format_query(res) if not args.json
              else json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    info = collect(root)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print_status(info)
    return 0


def cmd_check(args):
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"项目目录不存在：{root}")
        return 2
    res = run_check(root)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print_check(res)
    return 0 if res["ok"] else 1


def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "测试短剧"
        args = argparse.Namespace(root=str(root), title="测试短剧", episodes=2,
                                  aspect="9:16", model="seedance-2.5",
                                  form="drama", target=60)
        assert cmd_init(args) == 0
        assert (root / STUDIO_NAME).is_file()

        # 七目录骨架与控制文件
        for d in ("00_project", "00_inbox", "01_story", "02_script", "03_assets",
                  "04_performance", "05_shots", "06_prompts", "场景板"):
            assert (root / d).is_dir(), d
        for f in ("brief.md", "project-status.md", "routing.md"):
            assert (root / "00_project" / f).is_file(), f
        assert (root / "00_project" / "history").is_dir()
        assert collect(root)["layout"] == "v3"

        info = collect(root)
        assert [s["key"] for s in info["stages"]] == list(STAGE_KEYS)
        assert len(info["stages"]) == 10, len(info["stages"])
        assert info["stages"][0]["name"] == "概念锚定"
        assert info["stages"][0]["status"] == "pending", info["stages"][0]
        assert info["next"]["key"] == "concept"
        # v3 下世界观与表演是可选段：未写不阻塞
        assert info["stages"][2]["status"] == "skip", info["stages"][2]
        assert info["stages"][6]["status"] == "skip", info["stages"][6]

        # 01 概念 → 02 角色：写了就推进
        (root / "01_story" / "synopsis.md").write_text(
            "# 概念\n\n一句话故事：茶棚里的两个人。\n", encoding="utf-8", newline="\n")
        info = collect(root)
        assert info["stages"][0]["status"] == "done"
        assert info["next"]["key"] == "characters", info["next"]
        (root / "01_story" / "characters.md").write_text(
            "# 角色\n\n@阿青：茶棚老板。\n", encoding="utf-8", newline="\n")
        # 模板占位不算完成
        (root / "01_story" / "worldbuilding.md").write_text(
            "# 世界观\n（待填）\n", encoding="utf-8", newline="\n")
        info = collect(root)
        assert info["stages"][1]["status"] == "done"
        assert info["stages"][2]["status"] == "skip", "占位文件不应算世界观完成"

        # 04 分场 → 05 剧本
        (root / "01_story" / "第1集" / "treatment.md").write_text(
            "# 第1集 分场\n\n场景1：内景·茶棚——日\n阿青擦杯子。\n",
            encoding="utf-8", newline="\n")
        info = collect(root)
        assert info["stages"][3]["done"] == 1, info["stages"][3]

        script = root / "02_script" / "第1集" / "剧本.md"
        script.write_text("# 第1集\n\n@阿青 推门进茶棚。\n\n@老周 抬头看他。\n",
                          encoding="utf-8", newline="\n")
        info = collect(root)
        sb_idx = [i for i, s in enumerate(info["stages"]) if s["key"] == "script"][0]
        assert info["stages"][sb_idx]["done"] == 1

        # 06 资产
        (root / "03_assets" / "阿青.png").write_bytes(b"")
        (root / "03_assets" / "老周.png").write_bytes(b"")
        info = collect(root)
        assert info["stages"][5]["status"] == "done", info["stages"][5]

        # 07 表演（可选段，写了就显示）
        (root / "04_performance" / "第1集" / "acting-v01.md").write_text(
            "# 第1集 表演\n\n@阿青：目标是想让对方先开口。\n",
            encoding="utf-8", newline="\n")
        info = collect(root)
        assert info["stages"][6]["status"] == "active", info["stages"][6]

        # 08 分镜 + 提示词
        sb = root / "05_shots" / "第1集" / "sb.json"
        sb.write_text(json.dumps({
            "grid_layout": "3x3",
            "shots": [{"shot_number": str(i),
                       "prompt_text": f"中景，@阿青 与 @老周 对视，第{i}个机位，冷调侧光，无时间码，无字幕。"}
                      for i in range(1, 10)]
        }, ensure_ascii=False), encoding="utf-8", newline="\n")
        (root / "06_prompts" / "第1集" / "cinedance-v01.md").write_text(
            "# 第1集 提示词\n\n## 镜 1\n中景，@阿青 站在茶棚门口。\n",
            encoding="utf-8", newline="\n")
        info = collect(root)
        assert info["stages"][7]["done"] == 1, info["stages"][7]
        assert any("提示词稿" in s["detail"] for s in info["stages"] if s["key"] == "storyboard")

        res = run_check(root)
        assert res["ok"], json.dumps(res, ensure_ascii=False, indent=2)

        # 09 出片 + 改稿回流提示
        vid_dir = root / "05_shots" / "第1集" / "视频段"
        vid_dir.mkdir(exist_ok=True)
        seg = vid_dir / "段01.mp4"
        seg.write_bytes(b"")
        old = float(int(datetime.now().timestamp())) - 3600
        os.utime(seg, (old, old))
        (root / "05_shots" / "第1集" / "grid01_定稿.png").write_bytes(b"")
        info = collect(root)
        assert info["stages"][8]["done"] == 1, info["stages"][8]
        assert any("分镜最新改动" in w for w in info["warnings"]), info["warnings"]

        # 10 后期
        (root / "05_shots" / "第1集" / "成片" / "第1集_成片.mp4").write_bytes(b"")
        info = collect(root)
        assert info["stages"][9]["done"] == 1, info["stages"][9]

        html = render_board(info)
        assert "短剧工作室 · 测试短剧" in html
        assert html.count('class="st ') == 10, html.count('class="st ')
        assert "阶段 01" in html and "阶段 10" in html
        assert "<script" not in html.lower(), "看板不应引入脚本"
        assert "http://" not in html and "https://" not in html, "看板不应有外部请求"
        assert cmd_board(argparse.Namespace(root=str(root), out=None)) == 0
        board = root / ".studio" / "board.html"
        assert board.is_file() and board.stat().st_size > 1000
        # XSS：标题里的尖括号必须被转义
        dirty = render_board({**info, "title": "<b>x</b>", "episodes_detail": []})
        assert "&lt;b&gt;x&lt;/b&gt;" in dirty and "<b>x</b>" not in dirty

    # ---- 单阶段跳做：不把焦点强行拉回最前面未完成段 ----
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "跳段项目"
        assert cmd_init(argparse.Namespace(root=str(root), title="跳段", episodes=1,
                                          aspect="9:16", model="seedance-2.5",
                                          form="drama", target=60)) == 0
        # 概念/角色/分场都没写，直接写了剧本与资产（单阶段模式）
        (root / "02_script" / "第1集" / "剧本.md").write_text(
            "# 第1集\n\n## 钩子\n她推开门。\n\n@阿青 站在门口。\n\n## 收尾\n脚步近了。\n",
            encoding="utf-8")
        (root / "03_assets" / "阿青.png").write_bytes(b"")
        info = collect(root)
        by_key = {s["key"]: s for s in info["stages"]}
        assert by_key["concept"]["status"] == "pending", by_key["concept"]
        assert by_key["script"]["status"] == "done", by_key["script"]
        # 焦点应落在 08（下游未开工的第一段），而不是 01
        assert info["next"]["key"] == "storyboard", info["next"]

    # ---- 异常时间戳不报假警 ----
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "时间戳项目"
        assert cmd_init(argparse.Namespace(root=str(root), title="时间戳", episodes=1,
                                          aspect="9:16", model="seedance-2.5",
                                          form="drama", target=60)) == 0
        odd = root / "05_shots" / "第1集" / "成片" / "第1集.mp4"
        odd.write_bytes(b"")
        os.utime(odd, (1000, 1000))
        assert "1970" not in " ".join(collect(root)["warnings"])

    # ---- 旧 v2 布局兼容 ----
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "旧布局项目"
        (root / "第1集" / "分镜" / "视频段").mkdir(parents=True)
        (root / "第1集" / "成片").mkdir(parents=True)
        (root / "素材").mkdir()
        (root / STUDIO_NAME).write_text(json.dumps(
            {"schema": 2, "form": "drama", "title": "旧布局", "episodes": 1},
            ensure_ascii=False), encoding="utf-8")
        (root / "第1集" / "剧本.md").write_text(
            "# 第1集\n\n@阿青 推门。\n\n@老周 抬头。\n", encoding="utf-8")
        (root / "素材" / "阿青.png").write_bytes(b"")
        (root / "第1集" / "分镜" / "sb.json").write_text(json.dumps({
            "grid_layout": "3x3",
            "shots": [{"shot_number": str(i),
                       "prompt_text": f"中景，@阿青 与 @老周 对视，第{i}个机位，冷调侧光，无时间码，无字幕。"}
                      for i in range(1, 10)]
        }, ensure_ascii=False), encoding="utf-8")
        (root / "第1集" / "分镜" / "视频段" / "段01.mp4").write_bytes(b"")

        info = collect(root)
        assert info["layout"] == "v2", info["layout"]
        assert len(info["stages"]) == 10
        # v2 没有上游创作段：标记为可跳过而不是 pending
        assert info["stages"][0]["status"] == "skip", info["stages"][0]
        assert info["stages"][3]["status"] == "skip", info["stages"][3]
        # 但剧本、资产、分镜、出片照常识别
        by_key = {s["key"]: s for s in info["stages"]}
        assert by_key["script"]["done"] == 1, by_key["script"]
        assert by_key["assets"]["status"] == "done", by_key["assets"]
        assert by_key["storyboard"]["done"] == 1, by_key["storyboard"]
        assert by_key["video"]["status"] == "done", by_key["video"]
        assert info["next"]["key"] == "post", info["next"]

    # ---- 短视频形态 ----
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "一条短片"
        args = argparse.Namespace(root=str(root), title="一条短片", episodes=1,
                                  aspect="9:16", model="seedance-2.5", form="short",
                                  target=45)
        assert cmd_init(args) == 0
        assert (root / "02_script" / "脚本.md").is_file()
        assert (root / "发布").is_dir()

        info = collect(root)
        assert info["form"] == "short"
        assert info["stages"][4]["name"] == "脚本台", info["stages"][4]
        assert info["stages"][9]["name"] == "发布台", info["stages"][9]
        assert info["stages"][4]["status"] == "pending"

        (root / "02_script" / "脚本.md").write_text("""# 短片

## 钩子
她把最后一枚硬币投进了自动售货机。

## 口播
""" + "字" * 190 + """

## 分镜
| 时间 | 画面 |
|---|---|
| 0-3s | 硬币落下的特写 |
| 3-10s | 售货机灯光亮起 |
| 10-20s | 她伸手取出东西 |
| 20-32s | 她转身走进雨里 |
| 32-45s | 空镜头，机器灯灭 |

## 封面文案
一枚硬币
## 话题标签
#城市 #短片
## 评论区引导
你最后一次投币是什么时候
""", encoding="utf-8", newline="\n")
        (root / "03_assets" / "硬币.png").write_bytes(b"")
        info = collect(root)
        by_key = {s["key"]: s for s in info["stages"]}
        assert by_key["script"]["done"] == 1, by_key["script"]
        assert by_key["assets"]["status"] == "done", by_key["assets"]
        assert by_key["storyboard"]["done"] == 1, by_key["storyboard"]

        # 发布台：只有成片没有发布包 -> 不算完成
        shots = root / "05_shots"
        (shots / "成片" / "成片.mp4").write_bytes(b"")
        info = collect(root)
        by_key = {s["key"]: s for s in info["stages"]}
        assert by_key["post"]["done"] == 0, by_key["post"]
        assert "发布" in by_key["post"]["detail"]
        (root / "发布" / "文案.md").write_text("发布", encoding="utf-8")
        info = collect(root)
        by_key = {s["key"]: s for s in info["stages"]}
        assert by_key["post"]["done"] == 1, by_key["post"]

        # check 串起 short_plan
        res = run_check(root)
        names = [r["name"] for r in res["results"]]
        assert any("short_plan" in n for n in names), names
        assert res["ok"], json.dumps(res, ensure_ascii=False, indent=2)

        # 超预算口播 -> 门禁失败
        (root / "02_script" / "脚本.md").write_text(
            (root / "02_script" / "脚本.md").read_text(encoding="utf-8").replace("字" * 190, "字" * 400),
            encoding="utf-8", newline="\n")
        res = run_check(root)
        assert not res["ok"], "超预算口播应让门禁失败"

        html = render_board(collect(root))
        assert "短视频工作室" in html
        assert "单条明细" in html and "发布包" in html
        assert html.count('class="st ') == 10

    # 成本视图：无台账不显示，有台账显示已花与浪费
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "成本项目"
        assert cmd_init(argparse.Namespace(root=str(root), title="成本", episodes=1,
                                          aspect="9:16", model="seedance-2.5",
                                          form="drama", target=60)) == 0
        info = collect(root)
        assert info["cost"] is None, "无台账时 cost 应为 None"

        sys.path.insert(0, str(HERE))
        from task_ledger import cmd_submit, cmd_result, ledger_path
        cmd_submit(argparse.Namespace(root=str(root), unit="第1集", shot="组01",
                                     prompt_sha="abc", model="seedance-2.5",
                                     est_credits=130, note=None, force=False))
        cmd_result(argparse.Namespace(root=str(root), unit="第1集", shot="组01",
                                     status="failed", actual_credits=130,
                                     artifact=None, note="审核"))
        cmd_submit(argparse.Namespace(root=str(root), unit="第1集", shot="组01",
                                     prompt_sha="abc", model="seedance-2.5",
                                     est_credits=130, note=None, force=False))
        cmd_result(argparse.Namespace(root=str(root), unit="第1集", shot="组01",
                                     status="success", actual_credits=130,
                                     artifact="段01.mp4", note=None))
        info = collect(root)
        c = info["cost"]
        assert c and c["spent"] == 130 and c["wasted"] == 130, c
        assert c["waste_ratio"] == 1.0, c
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_status(info)
        out = buf.getvalue()
        assert "成本：已花 130 分" in out, out
        assert "失败重抽 130 分" in out, out
        assert "超过 10% 重生预算" in out, out
        assert ledger_path(root).is_file()

    # 影响面：--impact 查询 + 派生索引过期告警
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "影响面项目"
        assert cmd_init(argparse.Namespace(root=str(root), title="影响面", episodes=1,
                                          aspect="9:16", model="seedance-2.5",
                                          form="drama", target=60)) == 0
        (root / "03_assets" / "阿青.png").write_bytes(b"")
        (root / "02_script" / "第1集" / "剧本.md").write_text(
            "# 第1集\n\n## 钩子\n她推开门，屋里空无一人。\n\n@阿青\n\n## 收尾\n"
            "门外传来脚步。\n", encoding="utf-8")
        ep = root / "05_shots" / "第1集"
        (ep / "视频段").mkdir(parents=True, exist_ok=True)
        (ep / "sb.json").write_text(json.dumps({"shots": [
            {"shot_number": "组01",
             "prompt_text": "中景，@阿青 站在门口。无时间码，无字幕。"}]},
            ensure_ascii=False), encoding="utf-8")
        (ep / "视频段" / "段01.mp4").write_bytes(b"")
        # manifest 的文件名相对分镜目录解析，故段文件也放一份在分镜目录下
        (ep / "组01.mp4").write_bytes(b"")

        sys.path.insert(0, str(HERE))
        from impact_graph import build as ig_build
        ig_build(root)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_status(argparse.Namespace(root=str(root), json=False, impact="@阿青"))
        assert rc == 0, rc
        out = buf.getvalue()
        assert "@阿青" in out and "1 镜" in out, out

        # 未找到的引用返回 1
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_status(argparse.Namespace(root=str(root), json=False, impact="@不存在"))
        assert rc == 1, rc

        # 派生索引过期：改分镜不改索引 → check 给警告但不失败
        seg = ep / "sb.json"
        seg.write_text(json.dumps({"shots": [
            {"shot_number": "组01",
             "prompt_text": "中景，@阿青 站在门口，冷光。无时间码，无字幕。"}]},
            ensure_ascii=False), encoding="utf-8")
        future = seg.stat().st_mtime + 10
        os.utime(seg, (future, future))
        res = run_check(root)
        assert res["warnings"], "改分镜后应报 _impact.json 过期"
        assert any("_impact.json 已过期" in w for w in res["warnings"]), res["warnings"]
        assert res["ok"], ("过期是警告，不应让 check 失败：" +
                           json.dumps([r["name"] for r in res["results"] if not r["ok"]],
                                      ensure_ascii=False))

    # 原著索引：init --novel 建索引 + status 提示未分析章节 + 审查软提示
    with tempfile.TemporaryDirectory() as tmp:
        novel = Path(tmp) / "原著.txt"
        novel.write_text("".join(
            f"第{i}章 标题{i}\n\n他推开门，屋里空无一人。桌上放着一封信。\n\n"
            for i in range(1, 6)), encoding="utf-8", newline="\n")
        root = Path(tmp) / "原著项目"
        assert cmd_init(argparse.Namespace(root=str(root), title="原著", episodes=2,
                                          aspect="9:16", model="seedance-2.5",
                                          form="drama", target=60,
                                          novel=str(novel))) == 0
        idx = root / "_novel" / "index.json"
        assert idx.is_file(), "init --novel 应建索引"
        data = json.loads(idx.read_text(encoding="utf-8"))
        assert data["chapter_count"] == 5, data["chapter_count"]

        # status：有产物但无审查记录 → 软提示；未分析章节 → 提示
        (root / "03_assets" / "阿青.png").write_bytes(b"")
        data["unread"] = [4, 5]
        data["read_range"] = "第1-3章"
        idx.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_status(collect(root))
        out = buf.getvalue()
        assert "审查：本集尚无审查记录" in out, out
        assert "尚有 2 章未分析" in out, out

        # 有审查记录后不该再提示
        (root / "_reviews").mkdir()
        (root / "_reviews" / "第1集.md").write_text("# 审查记录\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_status(collect(root))
        assert "尚无审查记录" not in buf.getvalue(), buf.getvalue()

        # --json 可序列化不变量：collect() 全字段必须能 json.dumps（Path 漏转即在此炸）
        for label, proj in (("v3", root), ("v2", Path(HERE).parent / "examples" / "demo-multi-ep")):
            if not proj.is_dir():
                continue
            try:
                json.dumps(collect(proj), ensure_ascii=False)
            except TypeError as e:
                raise AssertionError(f"collect({label}) 结果不可 JSON 序列化：{e}") from e

    print("studio selftest: OK（十段路由 + 七目录 + v2 布局兼容 + 单阶段跳做 + 短视频 + "
          "口播预算 + 成本视图 + 影响面 + 原著索引/审查提示）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="短剧工作室总控：十段路由进度、门禁与改稿影响")
    ap.add_argument("--selftest", action="store_true", help="自检")
    sub = ap.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="初始化工作室项目")
    p_init.add_argument("root")
    p_init.add_argument("--title", default="")
    p_init.add_argument("--episodes", type=int, default=1)
    p_init.add_argument("--aspect", default="9:16")
    p_init.add_argument("--model", default="seedance-2.5")
    p_init.add_argument("--form", choices=FORMS, default="drama",
                        help="drama=多集短剧（默认）/ short=单条短视频")
    p_init.add_argument("--target", type=float, default=60,
                        help="短片目标时长（秒），仅 --form short 使用")
    p_init.add_argument("--novel", default="",
                        help="原著 txt 路径：初始化时顺带建结构索引（_novel/index.json）")

    p_status = sub.add_parser("status", help="查看五工位进度与当前焦点工位")
    p_status.add_argument("root")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument("--impact", default="",
                          help="查某素材/场景的改稿影响面（需先 impact_graph build）")

    p_check = sub.add_parser("check", help="跑分镜、引用、清单、场景板与短端口播预算机检")
    p_check.add_argument("root")
    p_check.add_argument("--json", action="store_true")

    p_board = sub.add_parser("board", help="生成单文件 HTML 工作室看板")
    p_board.add_argument("root")
    p_board.add_argument("--out", default=None, help="输出路径（默认 <项目>/.studio/board.html）")

    sub.add_parser("selftest", help="自检")

    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if args.cmd == "init":
        sys.exit(cmd_init(args))
    if args.cmd == "status":
        sys.exit(cmd_status(args))
    if args.cmd == "check":
        sys.exit(cmd_check(args))
    if args.cmd == "board":
        sys.exit(cmd_board(args))
    if args.cmd == "selftest":
        sys.exit(selftest())
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
