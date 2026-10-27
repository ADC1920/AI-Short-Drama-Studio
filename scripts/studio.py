#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""短剧工作室总控（ai-short-play-video-creation 技能 v2.0.0）。

把剧本、角色与场景、分镜、出片、后期五个工位收进一个项目目录，
用一份项目配置 + 实时扫盘给出工位进度、当前焦点工位与改稿影响提示。

用法:
    python studio.py init <项目目录> [--title 标题] [--episodes N] [--aspect 9:16] [--model seedance-2.5]
    python studio.py status <项目目录> [--json]
    python studio.py check <项目目录> [--json]
    python studio.py selftest

项目结构（兼容 init_project.py）:
    <项目>/
      studio.json              项目配置（仅手填项，进度实时扫盘）
      素材/                    角色/场景/道具参考图，文件名 = @引用名
      场景板/                  可选：场景单数据与图
      第1集/剧本.md
      第1集/分镜/              sb.json / 宫格 JSON / 定稿图 / _manifest.json / 视频段/
      第1集/成片/              拼接成片 mp4

退出码: 0=正常/检查通过, 1=检查有失败, 2=用法/路径错误
"""
import argparse
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
    "schema": 2,
    "form": "drama",
    "title": "",
    "aspect": "9:16",
    "model": "seedance-2.5",
    "episodes": 1,
    "scene_plate": None,
    "notes": "",
}

FORMS = ("drama", "short")
SCRIPT_NAMES = {"drama": "剧本.md", "short": "脚本.md"}

# 两种形态共用同一套工位键；差别在工位名（短剧按集推进，短视频单条推进）
STAGE_NAMES = {
    "drama": {"script": "剧本台", "assets": "角色与场景台", "storyboard": "分镜台",
              "video": "出片台", "post": "后期台"},
    "short": {"script": "脚本台", "assets": "素材台", "storyboard": "分镜台",
              "video": "出片台", "post": "发布台"},
}
STAGE_KEYS = ("script", "assets", "storyboard", "video", "post")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def episode_dirs(root: Path):
    out = []
    if not root.is_dir():
        return out
    for p in root.iterdir():
        m = EP_RE.match(p.name)
        if p.is_dir() and m:
            out.append((int(m.group(1)), p))
    return sorted(out)


def units(root: Path, cfg):
    """工位推进单位：短剧=每集一个目录，短视频=整个项目一条。

    两种形态的目录契约一致（脚本 / 分镜 / 素材 / 成片），
    所以下游所有扫盘逻辑不必分支，只有单位来源与工位名不同。
    """
    if (cfg.get("form") or "drama") == "short":
        return [{"label": "本片", "dir": root,
                 "script": root / SCRIPT_NAMES["short"]}]
    return [{"label": f"第{num}集", "dir": d,
             "script": d / SCRIPT_NAMES["drama"]} for num, d in episode_dirs(root)]


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


def storyboard_jsons(ep: Path):
    d = ep / "分镜"
    if not d.is_dir():
        return []
    return [p for p in d.glob("*.json") if p.name != "_manifest.json"]


def short_storyboard_root(root: Path):
    """短视频：分镜目录直接挂在项目根，且分镜表通常写在 脚本.md 里。"""
    out = []
    d = root / "分镜"
    if d.is_dir():
        out += [p for p in d.glob("*.json") if p.name != "_manifest.json"]
        out += [p for p in d.glob("*.md")]
    script = root / SCRIPT_NAMES["short"]
    if script.is_file():
        try:
            text = script.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        # 脚本里出现时间轴分镜表，即视为分镜已产出
        if re.search(r"\|\s*\d+(?:\.\d+)?\s*[-–~至]\s*\d+", text):
            out.append(script)
    return out


def video_segments(ep: Path):
    for d in (ep / "分镜" / "视频段", ep / "成片" / "视频段"):
        if d.is_dir():
            vids = list_files(d, VIDEO_EXTS)
            if vids:
                return vids
    return []


def final_videos(ep: Path):
    d = ep / "成片"
    if not d.is_dir():
        return []
    return [p for p in d.glob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS]


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


def collect(root: Path):
    cfg = load_config(root)
    form = cfg.get("form") or "drama"
    names = STAGE_NAMES[form]
    us = units(root, cfg)
    eps = episode_dirs(root)
    cfg_episodes = int(cfg.get("episodes") or 0)
    if form == "drama" and cfg_episodes < len(eps):
        cfg["episodes"] = len(eps)

    per = []
    for u in us:
        d = u["dir"]
        per.append({
            "label": u["label"],
            "num": len(per) + 1,
            "script": script_ready(u["script"]),
            "storyboard": [str(p.relative_to(root)) for p in (
                storyboard_jsons(d) if form == "drama" else short_storyboard_root(root))],
            "plates": [str(p.relative_to(root)) for p in list_files(d / "分镜", IMAGE_EXTS)],
            "segments": len(video_segments(d)),
            "final": len(final_videos(d)),
        })

    asset_files = list_files(root / "素材", IMAGE_EXTS)
    plate_files = [p for p in (root / "场景板").rglob("*")] if (root / "场景板").is_dir() else []
    plate_files = [p for p in plate_files if p.is_file()]
    pub = publish_files(root)

    total = len(us) if us else 1
    stages = []

    script_done = sum(1 for x in per if x["script"])
    unit_word = "集剧本" if form == "drama" else "条脚本"
    stages.append(stage("script", script_done, total,
                        f"{script_done}/{total} {unit_word}就位"
                        if us else f"尚无 {SCRIPT_NAMES[form]}", names))

    if asset_files:
        extra = f" · 场景板 {len(plate_files)} 件" if form == "drama" else ""
        stages.append(stage("assets", 1, 1, f"素材 {len(asset_files)} 件{extra}", names))
    else:
        stages.append(stage("assets", 0, 1, "素材/ 为空", names))

    sb_done = sum(1 for x in per if x["storyboard"])
    plate_done = sum(1 for x in per if x["plates"])
    sb_word = "分镜 JSON" if form == "drama" else "分镜表"
    stages.append(stage("storyboard", sb_done, total,
                        f"{sb_done}/{total} {sb_word} · {plate_done} 份定稿图"
                        if us else "尚无分镜目录", names))

    seg_total = sum(x["segments"] for x in per)
    vid_done = sum(1 for x in per if x["segments"] > 0)
    if form == "short" and not seg_total:
        # 单条形态常直接把逐镜片段放 成片/；出片台与发布台用同一判据，避免两处打架
        seg_total = sum(x["final"] for x in per)
        vid_done = 1 if seg_total else 0
    stages.append(stage("video", vid_done, total,
                        f"{seg_total} 段视频 · {vid_done}/{total} 有产出"
                        if us else "尚无成片目录", names))

    if form == "short":
        # 短视频的发布台=成片齐 + 发布包齐，两者缺一即未完成
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

    next_stage = next((s for s in stages if s["status"] != "done"), None)
    warnings = impact_warnings(root, us)

    return {
        "project": str(root),
        "form": form,
        "title": cfg["title"],
        "aspect": cfg.get("aspect", ""),
        "model": cfg.get("model", ""),
        "episodes": len(eps) if form == "drama" else 1,
        "configured_episodes": cfg["episodes"],
        "publish_files": len(pub),
        "stages": stages,
        "next": next_stage,
        "warnings": warnings,
        "episodes_detail": per,
    }


def stage(key, done, total, detail, names):
    if total <= 0:
        total = 1
    if done >= total:
        status = "done"
    elif done > 0:
        status = "active"
    else:
        status = "pending"
    return {"key": key, "name": names[key],
            "done": done, "total": total, "status": status, "detail": detail}


def impact_warnings(root: Path, us):
    out = []
    # 低于此值视为异常时间戳（拷贝/解压/时钟错乱），不参与先后比较，避免报假警
    sane = 946684800.0  # 2000-01-01
    asset_dirs = [root / "素材", root / "场景板"]
    asset_new = newest(asset_dirs)
    final_old = oldest([u["dir"] / "成片" for u in us])
    if (asset_new and final_old and asset_new > sane and final_old > sane
            and asset_new > final_old):
        out.append(f"资产最新改动 {fmt_time(asset_new)} 晚于成片 {fmt_time(final_old)}：成片可能过期，改稿后按工位回流")
    sb_files = []
    for u in us:
        sb_files += [p for p in (u["dir"] / "分镜").glob("*")
                     if p.is_file() and p.suffix.lower() in (SB_EXTS | IMAGE_EXTS)]
    sb_new = max((p.stat().st_mtime for p in sb_files), default=None)
    seg_old = oldest([u["dir"] / "分镜" / "视频段" for u in us])
    if (sb_new and seg_old and sb_new > sane and seg_old > sane
            and sb_new > seg_old):
        out.append(f"分镜最新改动 {fmt_time(sb_new)} 晚于视频段 {fmt_time(seg_old)}：已有视频段可能过期")
    return out


def print_status(info):
    form_label = {"drama": "短剧", "short": "短视频"}.get(info["form"], info["form"])
    print(f"{'短剧' if info['form'] == 'drama' else '短视频'}工作室 · 《{info['title']}》")
    print(f"项目：{info['project']}")
    scope = f"{info['episodes']} 集" if info["form"] == "drama" else "单条"
    print(f"形态 {form_label} · 画幅 {info['aspect']} · 模型 {info['model']} · {scope}\n")
    print(f"{'工位':<14}{'进度':<12}{'状态':<8}说明")
    label = {"done": "完成", "active": "进行中", "pending": "待开始"}
    for i, s in enumerate(info["stages"], 1):
        prog = f"{s['done']}/{s['total']}"
        print(f"{i} {s['name']:<11}{prog:<12}{label[s['status']]:<8}{s['detail']}")
    nxt = info["next"]
    print()
    print(f"当前焦点工位：{nxt['name']}（{nxt['detail']}）" if nxt else "五个工位产物齐备，进入整体验收。")
    if info["warnings"]:
        print("\n改稿提示：")
        for w in info["warnings"]:
            print(f"  - {w}")


def run_check(root: Path):
    cfg = load_config(root)
    form = cfg.get("form") or "drama"
    us = units(root, cfg)
    checks = []
    py = sys.executable

    for u in us:
        for sb in storyboard_jsons(u["dir"]):
            checks.append((f"validate_storyboard {sb.relative_to(root)}",
                           [py, str(HERE / "validate_storyboard.py"), str(sb, ), "--no-log"]))
    if form == "short":
        for sb in short_storyboard_root(root):
            if sb.suffix.lower() == ".json":
                checks.append((f"validate_storyboard {sb.relative_to(root)}",
                               [py, str(HERE / "validate_storyboard.py"), str(sb), "--no-log"]))

    if (root / "素材").is_dir():
        checks.append(("check_refs 素材与 @引用",
                       [py, str(HERE / "check_refs.py"), str(root)]))

    for u in us:
        d = u["dir"] / "分镜"
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
        script = root / SCRIPT_NAMES["short"]
        if script.is_file():
            cmd = [py, str(HERE / "short_plan.py"), "--script", str(script)]
            if target:
                cmd += ["--target", str(target)]
            checks.append(("short_plan 口播时长预算", cmd))
        else:
            checks.append(("short_plan 口播时长预算（缺 脚本.md）", None))

    results = []
    for name, cmd in checks:
        if cmd is None:
            results.append({"name": name, "ok": False, "exit": 2, "output": "缺少必需文件"})
            continue
        try:
            cp = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
            out = (cp.stdout or "") + (cp.stderr or "")
            results.append({"name": name, "ok": cp.returncode == 0,
                            "exit": cp.returncode, "output": out.strip()[-1200:]})
        except subprocess.TimeoutExpired:
            results.append({"name": name, "ok": False, "exit": 124, "output": "超时（180s）"})
        except OSError as e:
            results.append({"name": name, "ok": False, "exit": 2, "output": str(e)})

    return {"project": str(root), "results": results,
            "ok": all(r["ok"] for r in results) if results else True}


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
.track{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:28px 0 24px}
.st{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}
.st.now{border-color:var(--active);box-shadow:0 0 0 1px rgba(210,153,34,.35)}
.st.done .dot{background:var(--done)}
.st.active .dot{background:var(--active)}
.st.pending{background:#14171d;border-color:rgba(255,255,255,.06)}
.st.pending .no{color:#5d646e}
.st.pending .nm{color:#b9c1cc}
.st.pending .prog{color:#8b949e}
.st.pending .det{color:#7d8590}
.st.pending .dot{background:var(--wait)}
.st .no{color:var(--faint);font-size:11px;letter-spacing:.08em}
.st .nm{margin:4px 0 10px;font-size:15px;font-weight:600}
.st .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;
vertical-align:middle}
.st .prog{font-variant-numeric:tabular-nums;font-size:20px;font-weight:600}
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
    label = {"done": "完成", "active": "进行中", "pending": "待开始"}
    now_key = info["next"]["key"] if info["next"] else None
    is_short = info.get("form") == "short"
    kind = "短视频工作室" if is_short else "短剧工作室"
    cells = []
    for i, s in enumerate(info["stages"], 1):
        cls = s["status"] + (" now" if s["key"] == now_key else "")
        cells.append(
            f'<div class="st {cls}"><div class="no">工位 {i}</div>'
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
                f'<td class="{"y" if e["script"] else "n"}">{"有" if e["script"] else "—"}</td>'
                f'<td class="num{" y" if e["storyboard"] else " n"}">{len(e["storyboard"])}</td>'
                f'<td class="num{" y" if e["plates"] else " n"}">{len(e["plates"])}</td>'
                f'<td class="num{" y" if e["segments"] else " n"}">{e["segments"]}</td>'
                f'<td class="num{" y" if e["final"] else " n"}">{e["final"]}</td></tr>')
        ep_table = ("<table><tr><th>集</th><th>剧本</th><th>分镜JSON</th><th>关键帧</th>"
                    "<th>视频段</th><th>成片</th></tr>" + "".join(rows) + "</table>"
                    if rows else '<p class="empty">还没有分集目录。先跑 '
                                 '<code>studio.py init</code> 建项目。</p>')
        card_title = "分集明细"

    if info["warnings"]:
        warn_html = "".join(f'<p class="warn">{esc(w)}</p>' for w in info["warnings"])
    else:
        warn_html = '<p class="empty">资产与分镜均早于下游产物，没有待回流的改稿。</p>'

    nxt = info["next"]
    if nxt:
        cmd = ("python scripts/studio.py check ." if not is_short
               else "python scripts/short_plan.py --script 脚本.md")
        next_html = (f'<div class="next">当前焦点工位：<b>{esc(nxt["name"])}</b>'
                     f'<span class="hint">{esc(nxt["detail"])}</span>'
                     f'<code class="cmd">{cmd}</code>'
                     f'<span class="hint">跑门禁，全绿再往下走。</span></div>')
    else:
        next_html = ('<div class="next">五个工位产物齐备，进入整体验收：'
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


def cmd_init(args):
    root = Path(args.root).resolve()
    cfg_file = root / STUDIO_NAME
    already = cfg_file.is_file()
    form = args.form
    root.mkdir(parents=True, exist_ok=True)
    (root / "素材").mkdir(exist_ok=True)
    (root / "场景板").mkdir(exist_ok=True)

    if form == "short":
        (root / "分镜").mkdir(exist_ok=True)
        (root / "成片").mkdir(exist_ok=True)
        (root / "发布").mkdir(exist_ok=True)
        script = root / SCRIPT_NAMES["short"]
        if not script.exists():
            script.write_text(
                "# 短视频脚本\n\n"
                "（本文件=短端口播稿+分镜表。目标时长写进 studio.json 的 target_seconds；"
                "出场人物/场景用 @ 引用名，素材放 素材/。）\n", encoding="utf-8", newline="\n")
    else:
        for ep in range(1, max(1, args.episodes) + 1):
            d = root / f"第{ep}集"
            (d / "分镜").mkdir(parents=True, exist_ok=True)
            (d / "成片").mkdir(parents=True, exist_ok=True)
            script = d / SCRIPT_NAMES["drama"]
            if not script.exists():
                script.write_text(
                    f"# 第{ep}集 剧本\n\n（本集剧本：按剧情节点切分，每集有独立的钩子与收尾。出场角色/场景用 @ 引用名。）\n",
                    encoding="utf-8", newline="\n")

    if not already:
        cfg = dict(CONFIG_DEFAULTS)
        cfg.update({"form": form, "title": args.title or root.name,
                    "aspect": args.aspect, "model": args.model,
                    "episodes": args.episodes, "created": now()})
        if form == "short":
            cfg["target_seconds"] = args.target
        save_config(root, cfg)

    kind = "短视频工作室" if form == "short" else "短剧工作室"
    print(f"{kind}已就绪：{root}")
    if already:
        print(f"已有 {STUDIO_NAME}，保留原配置{'' if form == 'drama' else '（形态以配置为准）'}，只补齐目录。")
    if form == "short":
        print(f"工位目录：素材/ · 分镜/ · 成片/ · 发布/ · {SCRIPT_NAMES['short']}")
        print(f"目标时长 {args.target}s；下一步：写 {SCRIPT_NAMES['short']} → python studio.py status .")
    else:
        print(f"工位目录：素材/ · 场景板/ · 第1..{max(1, args.episodes)}集/{{剧本.md,分镜/,成片/}}")
        print("下一步：写第1集剧本 → python studio.py status .")
    return 0


def cmd_status(args):
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"项目目录不存在：{root}")
        return 2
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
        assert (root / "场景板").is_dir()

        info = collect(root)
        assert [s["key"] for s in info["stages"]] == list(STAGE_KEYS)
        assert info["stages"][0]["name"] == "剧本台"
        assert info["stages"][0]["status"] == "pending", info["stages"][0]
        assert info["next"]["key"] == "script"

        script = root / "第1集" / "剧本.md"
        script.write_text("# 第1集\n\n@阿青 推门进茶棚。\n\n@老周 抬头看他。\n",
                          encoding="utf-8", newline="\n")
        info = collect(root)
        assert info["stages"][0]["done"] == 1
        assert info["stages"][0]["status"] == "active"

        (root / "素材" / "阿青.png").write_bytes(b"")
        (root / "素材" / "老周.png").write_bytes(b"")
        sb = root / "第1集" / "分镜" / "sb.json"
        sb.write_text(json.dumps({
            "grid_layout": "3x3",
            "shots": [{"shot_number": str(i),
                       "prompt_text": f"中景，@阿青 与 @老周 对视，第{i}个机位，冷调侧光，无时间码，无字幕。"}
                      for i in range(1, 10)]
        }, ensure_ascii=False), encoding="utf-8", newline="\n")

        info = collect(root)
        assert info["stages"][1]["status"] == "done"
        assert info["stages"][2]["done"] == 1, info["stages"][2]

        res = run_check(root)
        assert res["ok"], json.dumps(res, ensure_ascii=False, indent=2)

        vid_dir = root / "第1集" / "分镜" / "视频段"
        vid_dir.mkdir()
        seg = vid_dir / "段01.mp4"
        seg.write_bytes(b"")
        old = float(int(datetime.now().timestamp())) - 3600
        os.utime(seg, (old, old))
        (root / "第1集" / "分镜" / "grid01_定稿.png").write_bytes(b"")
        info = collect(root)
        assert info["stages"][3]["done"] == 1
        assert any("分镜最新改动" in w for w in info["warnings"]), info["warnings"]

        # 异常时间戳（拷贝/解压）不报假警
        weird = root / "第5集"
        (weird / "分镜").mkdir(parents=True)
        (weird / "成片").mkdir()
        odd = weird / "成片" / "第5集.mp4"
        odd.write_bytes(b"")
        os.utime(odd, (1000, 1000))
        assert "1970" not in " ".join(collect(root)["warnings"])

        html = render_board(info)
        assert "短剧工作室 · 测试短剧" in html
        assert html.count('class="st ') == 5, html.count('class="st ')
        assert "工位 1" in html and "工位 5" in html
        assert "<script" not in html.lower(), "看板不应引入脚本"
        assert "http://" not in html and "https://" not in html, "看板不应有外部请求"
        assert cmd_board(argparse.Namespace(root=str(root), out=None)) == 0
        board = root / ".studio" / "board.html"
        assert board.is_file() and board.stat().st_size > 1000
        # XSS：标题里的尖括号必须被转义
        dirty = render_board({**info, "title": "<b>x</b>", "episodes_detail": []})
        assert "&lt;b&gt;x&lt;/b&gt;" in dirty and "<b>x</b>" not in dirty

    # ---- 短视频形态 ----
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "一条短片"
        args = argparse.Namespace(root=str(root), title="一条短片", episodes=1,
                                  aspect="9:16", model="seedance-2.5", form="short",
                                  target=45)
        assert cmd_init(args) == 0
        assert (root / "脚本.md").is_file()
        assert (root / "发布").is_dir()

        info = collect(root)
        assert info["form"] == "short"
        assert info["stages"][0]["name"] == "脚本台", info["stages"][0]
        assert info["stages"][4]["name"] == "发布台", info["stages"][4]
        assert info["stages"][0]["status"] == "pending"

        (root / "脚本.md").write_text("""# 短片

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
        (root / "素材" / "硬币.png").write_bytes(b"")
        info = collect(root)
        assert info["stages"][0]["done"] == 1
        assert info["stages"][1]["status"] == "done"
        assert info["stages"][2]["done"] == 1, info["stages"][2]

        # 发布台：只有成片没有发布包 -> 不算完成
        (root / "成片" / "成片.mp4").write_bytes(b"")
        info = collect(root)
        assert info["stages"][4]["done"] == 0, info["stages"][4]
        assert "发布" in info["stages"][4]["detail"]
        (root / "发布" / "文案.md").write_text("发布", encoding="utf-8")
        info = collect(root)
        assert info["stages"][4]["done"] == 1, info["stages"][4]

        # check 串起 short_plan
        res = run_check(root)
        names = [r["name"] for r in res["results"]]
        assert any("short_plan" in n for n in names), names
        assert res["ok"], json.dumps(res, ensure_ascii=False, indent=2)

        # 超预算口播 -> 门禁失败
        (root / "脚本.md").write_text(
            (root / "脚本.md").read_text(encoding="utf-8").replace("字" * 190, "字" * 400),
            encoding="utf-8", newline="\n")
        res = run_check(root)
        assert not res["ok"], "超预算口播应让门禁失败"

        html = render_board(collect(root))
        assert "短视频工作室" in html
        assert "单条明细" in html and "发布包" in html
        assert html.count('class="st ') == 5
    print("studio selftest: OK（短剧形态 + 短视频形态 + 短端口播预算门禁）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="短剧工作室总控：五工位进度、门禁与改稿影响")
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

    p_status = sub.add_parser("status", help="查看五工位进度与当前焦点工位")
    p_status.add_argument("root")
    p_status.add_argument("--json", action="store_true")

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
