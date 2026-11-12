# -*- coding: utf-8 -*-
"""改稿影响面依赖图（ai-short-drama-studio 技能）。

用途：把「改了某个角色/场景，哪些镜头和视频段要重出」从文件时间粗判
升级为按引用算出的精确清单。这是工作室改稿回流表的代码化。

数据来源（三份已存在的产物，不新建事实源）：
  1. 分镜 JSON 的 prompts / prompt_text → 抽 @引用名 与 S-* 场景引用
  2. <项目>/_manifest.json → 每段对应的镜号与产物文件名
  3. <项目>/素材/ 与 场景板/ → 判断引用是否断链

数据文件：<项目>/_impact.json（派生文件，可随时删、可重建，不入 git）

用法：
  python scripts/impact_graph.py build <项目> [--json]
  python scripts/impact_graph.py query <项目> --asset @顾寒 [--json]
  python scripts/impact_graph.py query <项目> --scene S-01@day-crowd [--json]
  python scripts/impact_graph.py selftest

约定：
  - _impact.json 不是事实源：事实源是分镜 JSON 与 _manifest.json，本文件只是索引。
  - query 除了列镜号与段，还按改稿回流表推出「成片也要重剪」，不让人自己查表。
  - 与 check_refs 同源：断链判定用同一套正则与忽略规则，两脚本结论必须一致。
"""
import argparse
import json
import os
import sys
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMPACT_NAME = "_impact.json"
SKIP_JSON = {"studio.json", "_manifest.json", "_impact.json"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
EP_RE_DIGITS = "0123456789"


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ref_re():
    """@引用正则与忽略规则从 check_refs 导入；失败则用内置兜底（同源重复定义）。"""
    sys.path.insert(0, str(HERE))
    try:
        import check_refs
        return check_refs.REF_RE, check_refs.is_ignored
    except ImportError:
        import re
        return re.compile(r"@([A-Za-z0-9_\-\u4e00-\u9fff]+)"), lambda n: len(n) > 40


def _scene_re():
    """S-* 场景引用正则从 check_scene_plates 导入；失败则兜底。"""
    sys.path.insert(0, str(HERE))
    try:
        from check_scene_plates import SCENE_REF_RE
        return SCENE_REF_RE
    except ImportError:
        import re
        return re.compile(r"S-\d{2,}(?:@[a-z0-9][a-z0-9-]*?)?")


def episode_units(root: Path):
    """集目录列表：短剧为 第1集/第2集…，短视频为根目录本身。"""
    out = []
    for d in sorted(root.iterdir() if root.is_dir() else []):
        if d.is_dir() and d.name.startswith("第") and d.name.endswith("集"):
            out.append({"label": d.name, "dir": d})
    if not out and (root / "分镜").is_dir():
        out.append({"label": "single", "dir": root})
    return out


def storyboard_files(unit_dir: Path):
    d = unit_dir / "分镜"
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.json")
                  if p.is_file() and p.name not in SKIP_JSON)


def extract_prompts(path: Path):
    """从分镜 JSON 抽 {镜号: 提示词文本}。字段名各版本不一，按优先级取。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    shots = data.get("shots") if isinstance(data, dict) else None
    if not isinstance(shots, list):
        return {}
    out = {}
    for i, sh in enumerate(shots, 1):
        if not isinstance(sh, dict):
            continue
        key = str(sh.get("shot_number") or sh.get("shot") or i).strip()
        parts = [str(sh.get(k) or "") for k in
                 ("prompt_text", "prompt", "text", "content")]
        text = "\n".join(p for p in parts if p)
        if not text and isinstance(sh.get("prompt"), dict):
            text = "\n".join(str(v) for v in sh["prompt"].values() if v)
        if key and text:
            out[key] = text
    return out


def load_manifest(unit_dir: Path):
    """读 _manifest.json，返回 {镜号: 段文件名}。无清单返回空。"""
    mf = unit_dir / "分镜" / "_manifest.json"
    if not mf.is_file():
        return {}
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    out = {}
    for s in data.get("shots") or []:
        if isinstance(s, dict) and s.get("shot"):
            out[str(s["shot"])] = s.get("file") or ""
    return out


def collect_assets(root: Path):
    """素材名 -> 相对路径。"""
    out = {}
    d = root / "素材"
    if not d.is_dir():
        return out
    for f in sorted(d.iterdir()):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
            out.setdefault(f.stem, str(f.relative_to(root)).replace(os.sep, "/"))
    return out


def build(root: Path):
    ref_re, is_ignored = _ref_re()
    scene_re = _scene_re()
    assets = collect_assets(root)
    asset_index, scene_index, shot_index = {}, {}, {}
    orphans = set()

    for u in episode_units(root):
        unit = u["label"]
        segmap = load_manifest(u["dir"])
        prompts = {}
        for sb in storyboard_files(u["dir"]):
            prompts.update(extract_prompts(sb))
        # 分镜 JSON 抽不出时，退回看分镜 md 里的提示词行
        if not prompts:
            md = u["dir"] / "分镜"
            for p in sorted(md.glob("*.md")) if md.is_dir() else []:
                prompts[p.stem] = p.read_text(encoding="utf-8", errors="replace")
        for shot, text in prompts.items():
            shot_key = f"{unit}/{shot}"
            # 先剔除 S-01@day-crowd 这类场景 state，否则其中的 @day-crowd 会被
            # 素材正则当成引用名，误报断链（场景 state 的 @ 是 state 分隔符，不是引用）
            scenes = sorted(set(scene_re.findall(text)))
            text_wo_scenes = scene_re.sub(" ", text)
            refs = sorted({m for m in ref_re.findall(text_wo_scenes) if not is_ignored(m)})
            seg_file = segmap.get(shot, "")
            seg = f"{unit}/分镜/视频段/{seg_file}" if seg_file else ""
            shot_index[shot_key] = {
                "refs": [f"@{r}" for r in refs],
                "scenes": scenes,
                "segment": seg,
            }
            for r in refs:
                if r not in assets:
                    orphans.add(f"@{r}")
                e = asset_index.setdefault(f"@{r}", {
                    "kind": "character",
                    "source": assets.get(r, ""),
                    "shots": [], "segments": [],
                })
                e["shots"].append(shot_key)
                if seg:
                    e["segments"].append(seg)
            for sc in scenes:
                e = scene_index.setdefault(sc, {
                    "kind": "scene", "shots": [], "segments": [],
                })
                e["shots"].append(shot_key)
                if seg:
                    e["segments"].append(seg)

    # 已出成片的集列表，query 时用来推「成片需重剪」
    finals = []
    for u in episode_units(root):
        fd = u["dir"] / "成片"
        if fd.is_dir():
            for f in sorted(fd.glob("*.mp4")):
                finals.append(str(f.relative_to(root)).replace(os.sep, "/"))

    data = {
        "built": now(),
        "assets": asset_index,
        "scenes": scene_index,
        "shots": shot_index,
        "finals": finals,
        "orphans": sorted(orphans),
    }
    (root / IMPACT_NAME).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    return data


def load_impact(root: Path):
    p = root / IMPACT_NAME
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def query(data, name: str):
    """按素材名或场景 state 查影响面。返回 None 表示未找到。"""
    key = name if name.startswith("@") else f"@{name}"
    hit = data["assets"].get(key)
    kind = "asset"
    if hit is None:
        hit = data["scenes"].get(name)
        kind = "scene"
    if hit is None:
        return None
    units = sorted({s.split("/")[0] for s in hit["shots"]})
    finals = [f for f in data.get("finals", [])
              if any(f.startswith(u + "/") for u in units)]
    return {
        "name": name, "kind": kind, "source": hit.get("source", ""),
        "shots": hit["shots"], "segments": hit["segments"],
        "final_needs_recut": finals,
    }


def format_query(res):
    kind_label = {"asset": "素材", "scene": "场景"}[res["kind"]]
    lines = [f"{kind_label} {res['name']} 影响面（依赖图）："]
    if res.get("source"):
        lines.append(f"  资产：{res['source']}")
    lines.append(f"  {len(res['shots'])} 镜、{len(res['segments'])} 个视频段要重出")
    for s, seg in zip(res["shots"], res["segments"] or [""] * len(res["shots"])):
        lines.append(f"    {s}" + (f" → {seg}" if seg else " → （尚无视频段）"))
    if res["final_needs_recut"]:
        lines.append("  成片需重剪：" + "、".join(res["final_needs_recut"]))
    else:
        lines.append("  成片需重剪：（尚无成片）")
    return "\n".join(lines)


def cmd_build(args):
    root = Path(args.root)
    if not root.is_dir():
        print(f"项目目录不存在：{root}")
        return 2
    data = build(root)
    n_shots = len(data["shots"])
    n_assets = len(data["assets"])
    n_scenes = len(data["scenes"])
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"已建影响面索引：{root / IMPACT_NAME}")
    print(f"  {n_shots} 镜 · {n_assets} 个素材被引用 · {n_scenes} 个场景被引用")
    if data["orphans"]:
        print(f"  断链引用 {len(data['orphans'])} 个：" + "、".join(data["orphans"]))
        print("  （与 check_refs 同源判定，先补素材再重跑 build）")
    if n_shots == 0:
        print("  注意：未从分镜 JSON 抽出任何提示词——确认分镜文件有 shots 数组与 prompt 字段")
    return 0


def cmd_query(args):
    root = Path(args.root)
    data = load_impact(root)
    if data is None:
        print(f"未找到影响面索引：{root / IMPACT_NAME}（先跑 build）")
        return 2
    name = args.asset or args.scene or ""
    if not name:
        print("需指定 --asset 或 --scene")
        return 2
    res = query(data, name)
    if res is None:
        print(f"未找到引用：{name}（若刚改过分镜，先重跑 build）")
        return 1
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(format_query(res))
    return 0


def selftest():
    tmp = Path(tempfile.mkdtemp(prefix="ig_st_"))
    try:
        root = tmp / "项目"
        (root / "素材").mkdir(parents=True)
        (root / "素材" / "顾寒.png").write_bytes(b"stub")
        (root / "素材" / "奈奈.png").write_bytes(b"stub")
        ep = root / "第1集"
        (ep / "分镜" / "视频段").mkdir(parents=True)
        (ep / "成片").mkdir(parents=True)
        (ep / "成片" / "第1集.mp4").write_bytes(b"stub")

        shots = [
            {"shot_number": "组01", "prompt_text": "中景，@顾寒 与 @奈奈 对峙，S-01@day-crowd。"},
            {"shot_number": "组02", "prompt_text": "特写，@顾寒 抬眼。"},
            {"shot_number": "组03", "prompt_text": "空镜，S-01@day-crowd。"},
        ]
        (ep / "分镜" / "sb.json").write_text(
            json.dumps({"shots": shots}, ensure_ascii=False), encoding="utf-8")
        (ep / "分镜" / "视频段" / "段01.mp4").write_bytes(b"stub")
        (ep / "分镜" / "视频段" / "段02.mp4").write_bytes(b"stub")
        (ep / "分镜" / "_manifest.json").write_text(json.dumps({
            "shots": [{"shot": "组01", "file": "段01.mp4"},
                      {"shot": "组02", "file": "段02.mp4"}]
        }, ensure_ascii=False), encoding="utf-8")

        data = build(root)
        # 1 素材定位：精确 2 镜
        assert set(data["assets"]["@顾寒"]["shots"]) == {"第1集/组01", "第1集/组02"}, data["assets"]["@顾寒"]
        assert len(data["assets"]["@顾寒"]["segments"]) == 2
        res = query(data, "@顾寒")
        assert res["kind"] == "asset"
        assert set(res["shots"]) == {"第1集/组01", "第1集/组02"}
        assert res["final_needs_recut"] == ["第1集/成片/第1集.mp4"], res
        # 2 场景定位：走 scenes 分支，与素材分支同构
        res_sc = query(data, "S-01@day-crowd")
        assert res_sc["kind"] == "scene", res_sc
        assert set(res_sc["shots"]) == {"第1集/组01", "第1集/组03"}, res_sc
        assert "final_needs_recut" in res_sc
        # 3 断链入 orphans，不报错
        assert data["orphans"] == [], data["orphans"]
        (ep / "分镜" / "sb2.json").write_text(json.dumps({"shots": [
            {"shot_number": "组09", "prompt_text": "全景，@刀疤 入画。"}]}),
            encoding="utf-8")
        data2 = build(root)
        assert data2["orphans"] == ["@刀疤"], data2["orphans"]
        # 4 派生文件过期检测：改分镜后 rebuilt 时间变化
        old_built = data2["built"]
        import time as _t
        _t.sleep(1.05)
        data3 = build(root)
        assert data3["built"] != old_built, "重建应刷新 built 时间戳"
        # 5 与 check_refs 同源：断链集合一致
        sys.path.insert(0, str(HERE))
        from check_refs import collect_refs, check as refs_check, collect_assets
        assets = collect_assets(root / "素材")
        refs, line_texts, _contents = collect_refs([root])
        ref_errors, _warns = refs_check(assets, refs, line_texts)
        # 两边都应看到 @刀疤 为断链
        assert any("刀疤" in e for e in ref_errors), ref_errors
        assert "@刀疤" in data3["orphans"]
        # 6 未找到时返回码 1
        assert query(data3, "@不存在") is None
        # 7 无分镜时 build 不崩
        empty = tmp / "空项目"
        (empty / "素材").mkdir(parents=True)
        d_empty = build(empty)
        assert d_empty["shots"] == {} and d_empty["assets"] == {}
        print("selftest PASS（7 项：素材定位/场景定位/断链入 orphans/重建刷新/"
              "与 check_refs 同源/未找到/空项目）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
        return
    ap = argparse.ArgumentParser(description="改稿影响面依赖图")
    sub = ap.add_subparsers(dest="cmd")
    p1 = sub.add_parser("build", help="重建影响面索引")
    p1.add_argument("root"); p1.add_argument("--json", action="store_true")
    p2 = sub.add_parser("query", help="查某素材或场景的影响面")
    p2.add_argument("root")
    p2.add_argument("--asset", default="", help="素材名，如 @顾寒 或 顾寒")
    p2.add_argument("--scene", default="", help="场景 state，如 S-01@day-crowd")
    p2.add_argument("--json", action="store_true")
    sub.add_parser("selftest", help="自检")
    args = ap.parse_args()
    if args.cmd == "build":
        sys.exit(cmd_build(args))
    elif args.cmd == "query":
        sys.exit(cmd_query(args))
    else:
        ap.print_help()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
