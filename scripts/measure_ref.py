# -*- coding: utf-8 -*-
"""对标测量器（ai-short-drama-studio 技能）。

用途：把 SKILL.md 的「对标参考流程」从定性五维升级为可量化——对参考片与自家成片
跑同一套 ffprobe/ffmpeg 指标，出两栏对照表。测量口径一致是这套工具的核心约束：
参考片与自家片必须走同一个函数，才能比较。

依赖 ffmpeg / ffprobe（本机已装）。缺则明确报错退出，不做估算。

用法：
  python scripts/measure_ref.py probe <视频> [--out _refs/名字.json] [--threshold 0.35]
  python scripts/measure_ref.py diff <参考JSON> <本项目成片目录或视频> [--json]
  python scripts/measure_ref.py selftest

口径说明（写进每份 JSON，避免把工具观测当成影片事实）：
  - cuts 由场景检测（相邻帧灰度平均绝对差超过阈值）得出，不是人工标注的切点；
  - 阈值调高漏检、调低误检，数值应视为「同一把尺下的相对比较」，不是绝对真值；
  - 拿不到原片（只有截图/链接）时必须报无法测量，不估数。
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}
DEFAULT_THRESHOLD = 0.35
SAMPLE_FPS = 4          # 每秒采样帧数：切点检测的时间分辨率
MIN_SHOT_SECONDS = 0.6  # 短于此的「镜头」视为误检，与前一镜合并


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def have_ffmpeg():
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


def probe_basic(video: Path):
    """读时长/帧率/分辨率。缺 ffprobe 时抛错，不返回猜测值。"""
    if not have_ffmpeg():
        raise RuntimeError("需要 ffmpeg 与 ffprobe（PATH 中未找到）")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,duration",
         "-show_entries", "format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe 读不出该视频（文件可能损坏或不是视频）：{video}\n"
                           f"{out.stderr.strip()[:300]}")
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe 输出无法解析：{e}")
    streams = data.get("streams") or [{}]
    st = streams[0]
    dur = st.get("duration") or (data.get("format") or {}).get("duration")
    if not dur:
        raise RuntimeError(f"读不到时长：{video}")
    return {
        "duration": round(float(dur), 3),
        "frame_rate": st.get("r_frame_rate") or "",
        "resolution": f"{st.get('width', 0)}x{st.get('height', 0)}",
    }


def sample_frames(video: Path, tmp: Path, fps=SAMPLE_FPS):
    """按 fps 抽帧为小图，供切点检测。返回 [(时间秒, png路径)]。"""
    out_dir = tmp / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"fps={fps},scale=96:-1",
         str(out_dir / "f%05d.png")],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if cp.returncode != 0:
        raise RuntimeError(f"ffmpeg 抽帧失败: {video}\n{cp.stderr}")
    files = sorted(out_dir.glob("f*.png"))
    return [(round(i / fps, 3), p) for i, p in enumerate(files)]


def detect_cuts(frames, threshold=DEFAULT_THRESHOLD):
    """相邻采样帧灰度平均绝对差超过阈值 → 记切点。

    与 check_seams 的运动量算法同源（灰度差的绝对值均值），此处复制该行逻辑
    而非导入：跨脚本复用抽象的成本高于一行 np.mean(np.abs(a-b))，
    改口径时须同步 check_seams.motion_flow_metrics。
    """
    import numpy as np
    from PIL import Image
    cuts, prev = [], None
    for t, p in frames:
        try:
            cur = np.asarray(Image.open(p).convert("L"), dtype=np.float64)
        except OSError:
            continue
        if prev is not None and prev.shape == cur.shape:
            diff = float(np.mean(np.abs(cur - prev)))
            if diff > threshold:
                cuts.append(t)
        prev = cur
    return cuts


def shots_from_cuts(cuts, duration, min_len=MIN_SHOT_SECONDS):
    """切点 → 镜头时长列表。短于 min_len 的段视为误检，并入相邻段。"""
    marks = [0.0] + [c for c in cuts if 0 < c < duration] + [duration]
    raw = []
    for a, b in zip(marks, marks[1:]):
        seg = round(b - a, 3)
        if seg > 0:
            raw.append(seg)
    if not raw:
        return []
    # 先把过短段并入后一段（末段则并入前一段），再合并相邻的过短残留
    out = []
    for seg in raw:
        if seg < min_len and out:
            out[-1] = round(out[-1] + seg, 3)
        else:
            out.append(seg)
    # 首段过短时并入下一段（上面 out 为空时不吞，故单独处理）
    if len(out) > 1 and out[0] < min_len:
        out[1] = round(out[0] + out[1], 3)
        out.pop(0)
    return out


def probe_video(video: Path, threshold=DEFAULT_THRESHOLD):
    """完整测量：基础参数 + 切点 + 镜长统计。"""
    base = probe_basic(video)
    tmp = Path(tempfile.mkdtemp(prefix="mr_"))
    try:
        frames = sample_frames(video, tmp)
        cuts = detect_cuts(frames, threshold)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    lengths = shots_from_cuts(cuts, base["duration"])
    mean_len = round(sum(lengths) / len(lengths), 3) if lengths else 0.0
    return {
        "name": video.stem,
        "source": str(video),
        "probed": now(),
        "duration": base["duration"],
        "frame_rate": base["frame_rate"],
        "resolution": base["resolution"],
        "threshold": threshold,
        "cuts": cuts,
        "shot_lengths": lengths,
        "shot_count": len(lengths),
        "mean_shot_length": mean_len,
        "notes": f"切点由相邻帧灰度差 > {threshold} 检测（{SAMPLE_FPS}fps 采样），非人工标注",
    }


def load_or_probe(src: Path, threshold):
    """src 是 JSON 直接读，是视频则现场测量。"""
    if src.suffix.lower() == ".json":
        try:
            return json.loads(src.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            raise RuntimeError(f"参考 JSON 无法解析：{e}")
    if src.suffix.lower() in VIDEO_EXTS:
        return probe_video(src, threshold)
    raise RuntimeError(f"不支持的输入：{src}（需要视频文件或 probe 产出的 JSON）")


def videos_under(src: Path):
    if src.is_file() and src.suffix.lower() in VIDEO_EXTS:
        return [src]
    if src.is_dir():
        return sorted(p for p in src.rglob("*")
                      if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    return []


def diff_rows(ref, mine):
    """两组测量 → 对照行。四项指标，差列带符号。"""
    def delta(a, b):
        d = round(b - a, 3)
        return f"{d:+.3f}" if d else "0"

    return [
        ("总时长", f"{ref['duration']:.1f}s", f"{mine['duration']:.1f}s",
         delta(ref["duration"], mine["duration"])),
        ("平均镜长", f"{ref['mean_shot_length']:.2f}s", f"{mine['mean_shot_length']:.2f}s",
         delta(ref["mean_shot_length"], mine["mean_shot_length"])),
        ("镜头数", str(ref["shot_count"]), str(mine["shot_count"]),
         f"{mine['shot_count'] - ref['shot_count']:+d}"),
        ("切点数", str(len(ref["cuts"])), str(len(mine["cuts"])),
         f"{len(mine['cuts']) - len(ref['cuts']):+d}"),
    ]


def format_diff(ref, mine, rows):
    lines = [
        f"对标对照：参考《{ref.get('name','参考')}》 vs 本项目《{mine.get('name','成片')}》",
        "",
        f"{'指标':<10}{'参考片':<12}{'本项目':<12}差",
        "-" * 44,
    ]
    for name, a, b, d in rows:
        lines.append(f"{name:<10}{a:<12}{b:<12}{d}")
    lines.append("")
    lines.append("口径：两侧同一函数产出（相邻帧灰度差检测切点），数值可横向比较，"
                 "但切点是工具观测不是人工标注。")
    return "\n".join(lines)


def cmd_probe(args):
    src = Path(args.video)
    if not src.is_file():
        print(f"视频不存在：{src}")
        return 2
    if src.suffix.lower() not in VIDEO_EXTS:
        print(f"不支持的格式：{src.suffix}（支持 {'/'.join(sorted(VIDEO_EXTS))}）")
        return 2
    try:
        res = probe_video(src, args.threshold)
    except RuntimeError as e:
        print(str(e))
        return 2
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8", newline="\n")
        print(f"已写入 {out}")
    print(f"《{res['name']}》 {res['duration']}s · {res['resolution']} · "
          f"{res['shot_count']} 镜 · 平均镜长 {res['mean_shot_length']}s")
    print(res["notes"])
    return 0


def cmd_diff(args):
    src_ref = Path(args.ref)
    src_mine = Path(args.mine)
    for p in (src_ref, src_mine):
        if not p.exists():
            print(f"路径不存在：{p}")
            return 2
    try:
        ref = load_or_probe(src_ref, args.threshold)
    except RuntimeError as e:
        print(f"参考片无法测量：{e}")
        print("提示：只有截图或链接时无法测量——按 SKILL.md 纪律不估数，请先拿到原片。")
        return 2
    vids = videos_under(src_mine)
    if not vids:
        print(f"成片目录下无视频：{src_mine}")
        return 2
    try:
        mine = (load_or_probe(vids[0], args.threshold) if len(vids) == 1
                else probe_video(vids[0], args.threshold))
    except RuntimeError as e:
        print(f"本项目成片无法测量：{e}")
        return 2
    rows = diff_rows(ref, mine)
    if args.json:
        print(json.dumps({"ref": ref, "mine": mine,
                          "rows": [{"metric": r[0], "ref": r[1], "mine": r[2],
                                    "delta": r[3]} for r in rows]},
                         ensure_ascii=False, indent=2))
    else:
        print(format_diff(ref, mine, rows))
    return 0


def selftest():
    """合成测试片验证测量链路；无 ffmpeg 时跳过实拍部分。"""
    tmp = Path(tempfile.mkdtemp(prefix="mr_st_"))
    try:
        # 1 切点 → 镜长换算（纯逻辑，无依赖）
        cuts = [3.0, 7.0]
        lengths = shots_from_cuts(cuts, 10.0)
        assert lengths == [3.0, 4.0, 3.0], lengths
        # 2 过短镜头被合并（防误检）
        merged = shots_from_cuts([0.2, 3.0], 6.0)
        assert merged == [3.0, 3.0], merged
        # 3 零切点 → 单镜
        assert shots_from_cuts([], 5.0) == [5.0]
        # 4 差分计算
        ref = {"name": "ref", "duration": 68.2, "mean_shot_length": 3.1,
               "shot_count": 22, "cuts": [0] * 21}
        mine = {"name": "mine", "duration": 62.5, "mean_shot_length": 4.4,
                "shot_count": 14, "cuts": [0] * 13}
        rows = dict((r[0], r) for r in diff_rows(ref, mine))
        assert rows["总时长"][3] == "-5.700", rows
        assert rows["平均镜长"][3] == "+1.300", rows
        assert rows["镜头数"][3] == "-8", rows
        assert rows["切点数"][3] == "-8", rows

        # 5 实拍链路：三段不同纯色的测试片，切点应检出 2 个
        if not have_ffmpeg():
            print("selftest PASS（4 项纯逻辑；ffmpeg 不在 PATH，跳过实拍链路）")
            return
        segs = []
        colors = [("red", "0xCC2222"), ("green", "0x22CC22"), ("blue", "0x2222CC")]
        for i, (name, color) in enumerate(colors, 1):
            p = tmp / f"s{i}.mp4"
            cp = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                 "-i", f"color=c={color}:s=320x240:d=2:r=30",
                 "-pix_fmt", "yuv420p", str(p)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            assert cp.returncode == 0, cp.stderr
            segs.append(p)
        concat_list = tmp / "list.txt"
        concat_list.write_text("".join(f"file '{p.name}'\n" for p in segs),
                               encoding="utf-8")
        joined = tmp / "joined.mp4"
        cp = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(joined)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert cp.returncode == 0, cp.stderr

        res = probe_video(joined, 0.35)
        assert abs(res["duration"] - 6.0) < 0.2, res["duration"]
        assert len(res["cuts"]) == 2, f"应检出 2 个切点（纯色段边界），实际 {len(res['cuts'])}：{res['cuts']}"
        assert res["shot_count"] == 3, f"应 3 镜，实际 {res['shot_count']}"
        assert abs(sum(res["shot_lengths"]) - res["duration"]) < 0.2

        # 6 同一把尺：参考 JSON 与现场测量字段结构一致
        for key in ("duration", "frame_rate", "resolution", "cuts",
                    "shot_lengths", "shot_count", "mean_shot_length", "notes"):
            assert key in res, f"缺字段 {key}"
        print("selftest PASS（6 项：切点换算/短镜合并/单镜/差分/实拍链路/字段一致性）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
        return
    ap = argparse.ArgumentParser(description="对标测量器")
    sub = ap.add_subparsers(dest="cmd")
    p1 = sub.add_parser("probe", help="测量单个视频")
    p1.add_argument("video")
    p1.add_argument("--out", default="", help="写入 JSON 路径，如 _refs/参考A.json")
    p1.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    p2 = sub.add_parser("diff", help="参考片与本项目成片对照")
    p2.add_argument("ref", help="参考片视频或 probe 产出的 JSON")
    p2.add_argument("mine", help="本项目成片视频或成片目录")
    p2.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    p2.add_argument("--json", action="store_true")
    sub.add_parser("selftest", help="自检")
    args = ap.parse_args()
    if args.cmd == "probe":
        sys.exit(cmd_probe(args))
    elif args.cmd == "diff":
        sys.exit(cmd_diff(args))
    else:
        ap.print_help()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
