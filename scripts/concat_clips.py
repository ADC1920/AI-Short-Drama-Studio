# -*- coding: utf-8 -*-
"""分镜段拼接成片（后期台机械活）。

trim_clips.py 把每段裁到整拍之后，段与段的顺序拼接此前只有文档里的手敲命令。
本脚本接管三件事：

  ① 参数一致性核对（视频编码/分辨率/帧率/像素格式，可选音轨）——混参数直接
     `-c copy` 拼接会失败或花屏，这是手工拼接最常见的翻车点；
  ② 顺序拼接：参数一致走流复制（零损失、秒出）；
  ③ 切点列表导出：输出累积切点秒数，供 `check_seams.py --video --cuts` 与
     `qa_batch.py` 模式 B 复核接缝。

默认干跑只列计划；`--apply` 才拼接。参数不一致时默认拒绝，需
`--reencode-mismatch` 显式同意把异参数段重编码到基准段参数（有损、较慢）。
音轨默认丢弃（成片声音走后期配音轨），需保留加 `--keep-audio`。

用法：
  python scripts/concat_clips.py 第1集/分镜/视频段
  python scripts/concat_clips.py 第1集/分镜/视频段 --apply
  python scripts/concat_clips.py 第1集/分镜/视频段 --apply --reencode-mismatch
  python scripts/concat_clips.py 第1集/分镜/视频段 --out 第1集/成片/第1集.mp4 --cuts-out 切点.txt
  python scripts/concat_clips.py --selftest
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_rate(s):
    """'30000/1001' → 29.97；保留两位，避免 29.97 与 29.970001 误判。"""
    try:
        n, _, d = (s or "").partition("/")
        return round(float(n) / float(d or 1), 2)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(p: Path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                        "-of", "json", str(p)], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v:
        return None
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        dur = float(data.get("format", {}).get("duration") or v.get("duration") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    return {"codec": v.get("codec_name", ""), "w": int(v.get("width") or 0),
            "h": int(v.get("height") or 0), "fps": parse_rate(v.get("r_frame_rate", "")),
            "pix": v.get("pix_fmt", ""), "acodec": (a or {}).get("codec_name", ""),
            "dur": dur}


def natural_key(p: Path):
    """段NN 自然排序（段2 在段10 前）；「开场」永远排第一（与 qa_batch 一致）。"""
    parts = re.split(r"(\d+)", p.name)
    return (0 if "开场" in p.stem else 1,
            [(0, int(t)) if t.isdigit() else (1, t.lower()) for t in parts])


def collect(d: Path, pattern: str):
    return sorted((p for p in d.glob(pattern) if p.is_file()), key=natural_key)


FIELDS = (("codec", "编码"), ("w", "宽"), ("h", "高"), ("fps", "帧率"), ("pix", "像素格式"))


def diffs(base, cur, keep_audio):
    out = [(label, base[k], cur[k]) for k, label in FIELDS if base[k] != cur[k]]
    if keep_audio and base["acodec"] != cur["acodec"]:
        out.append(("音轨", base["acodec"] or "无", cur["acodec"] or "无"))
    return out


def reencode(src: Path, out: Path, base, keep_audio: bool):
    vf = (f"scale={base['w']}:{base['h']}:force_original_aspect_ratio=decrease,"
          f"pad={base['w']}:{base['h']}:(ow-iw)/2:(oh-ih)/2,fps={base['fps']:g}")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p"]
    if keep_audio and base["acodec"]:
        cmd += ["-c:a", "aac", "-ar", "44100", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd.append(str(out))
    r = subprocess.run(cmd, capture_output=True, text=True)
    return (r.returncode == 0), r.stderr.strip()[-300:]


def concat(files, out: Path, keep_audio: bool):
    tmp = Path(tempfile.mkdtemp(prefix="concat_"))
    try:
        lst = tmp / "list.txt"
        lines = []
        for f in files:
            p = str(Path(f).resolve()).replace("\\", "/").replace("'", "'\\''")
            lines.append(f"file '{p}'")
        lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
               "-i", str(lst), "-c", "copy"]
        if not keep_audio:
            cmd.append("-an")
        cmd.append(str(out))
        r = subprocess.run(cmd, capture_output=True, text=True)
        return (r.returncode == 0), r.stderr.strip()[-400:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def default_out(d: Path):
    """工位结构推断：…/第X集/分镜/视频段 → …/第X集/成片/第X集_成片.mp4。

    也认 trim_clips.py 的输出目录（视频段/裁切_5s），因为常见顺序是先裁整拍再
    对裁切目录拼接——不回溯的话成片会落在裁切子目录里，偏离工位结构。
    """
    vs = d.parent if d.name == "裁切_5s" else d
    if vs.name == "视频段" and vs.parent.name == "分镜":
        ep = vs.parent.parent
        return ep / "成片" / f"{ep.name}_成片.mp4"
    return d / "成片.mp4"


def run(args):
    d = Path(args.dir)
    if not d.is_dir():
        print(f"目录不存在：{d}")
        return 2
    files = collect(d, args.pattern)
    if not files:
        print(f"目录内无匹配文件：{d} / {args.pattern}")
        return 2

    infos = []
    for f in files:
        info = probe(f)
        if info is None:
            print(f"!! 无法读取视频流：{f.name}（跳过前请先确认文件完好）")
            return 2
        infos.append(info)

    base = infos[0]
    out = Path(args.out) if args.out else default_out(d)
    print(f"目录: {d}（{len(files)} 段）")
    print(f"基准: {files[0].name}  {base['codec']} {base['w']}x{base['h']}@"
          f"{base['fps']:g} pix={base['pix']} 音轨={base['acodec'] or '无'}")
    print(f"{'文件':<26}{'时长':>8}{'累积切点':>10}  说明")

    acc = 0.0
    bad = []
    for f, info in zip(files, infos):
        note = ""
        diff = diffs(base, info, args.keep_audio)
        if diff:
            note = "参数不一致：" + "、".join(f"{lb}={cv}(基准{bv})" for lb, bv, cv in diff)
            bad.append((f, diff))
        print(f"{f.name:<26}{info['dur']:>8.3f}{acc if acc else 0:>10.3f}  {note}")
        acc += info["dur"]

    total = acc
    print(f"\n参数一致性: {'通过（全部同源）' if not bad else f'{len(bad)} 段不一致'}")
    durs = [i["dur"] for i in infos]
    if max(durs) - min(durs) > 0.05:
        print(f"时长提示：各段 {min(durs):.3f}–{max(durs):.3f}s 不等——若本应等长，"
              f"先跑 trim_clips.py 裁整拍，否则切点会逐段漂移")
    print(f"音频: {'保留' if args.keep_audio else '丢弃（成片声音走后期配音轨；保留加 --keep-audio）'}")
    print(f"计划: 拼接 {len(files)} 段 → {out}  总时长约 {total:.3f}s")

    if not args.apply:
        print("\n干跑：加 --apply 执行拼接（源文件不动）")
        return 0

    work = list(files)
    if bad:
        if not args.reencode_mismatch:
            print(f"\n拒绝拼接：{len(bad)} 段参数与基准不一致，-c copy 会失败或花屏。")
            print("处置：①先统一生成参数重出该段（首选）；②或加 --reencode-mismatch "
                  "把异参数段重编码到基准参数（有损、较慢）。")
            return 3
        tmpdir = Path(tempfile.mkdtemp(prefix="concat_fix_"))
        try:
            print(f"\n重编码 {len(bad)} 段到基准参数…")
            fixed = dict(zip(files, work))
            for f, _ in bad:
                dst = tmpdir / f.name
                ok, err = reencode(f, dst, base, args.keep_audio)
                if not ok:
                    print(f"!! {f.name} 重编码失败：{err}")
                    return 4
                fixed[f] = dst
                print(f"   ✓ {f.name} → {base['w']}x{base['h']}@{base['fps']:g}")
            work = [fixed[f] for f in files]
            out.parent.mkdir(parents=True, exist_ok=True)
            ok, err = concat(work, out, args.keep_audio)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        ok, err = concat(work, out, args.keep_audio)

    if not ok:
        print(f"!! 拼接失败：{err}")
        return 4

    real = probe(out)
    if real is None:
        print(f"!! 成片不可读：{out}")
        return 4
    drift = real["dur"] - total
    flag = "✓" if abs(drift) <= 0.1 * max(1, len(files)) else "!!"
    print(f"{flag} 成片：{out}  {real['w']}x{real['h']}@{real['fps']:g}  "
          f"{real['dur']:.3f}s（计划 {total:.3f}s，偏差 {drift:+.3f}s）")

    if args.cuts_out:
        cuts = []
        acc = 0.0
        for info in infos[:-1]:
            acc += info["dur"]
            cuts.append(acc)
        cp = Path(args.cuts_out)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(",".join(f"{c:.3f}" for c in cuts), encoding="utf-8")
        print(f"切点列表：{cp}（{len(cuts)} 个）——复核接缝用 "
              f"check_seams.py --video \"{out}\" --cuts \"{','.join(f'{c:.3f}' for c in cuts)}\"")
    return 0


def selftest():
    """合成段验证自然排序、切点导出与异参数重编码；无 ffmpeg 时跳过。"""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("selftest SKIP（未检测到 ffmpeg/ffprobe，安装后重跑）")
        return
    tmp = Path(tempfile.mkdtemp(prefix="concat_st_"))
    try:
        def make(path: Path, sec: float, size: str):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", f"testsrc=duration={sec}:size={size}:rate=60",
                            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
                            str(path)], capture_output=True, check=True)

        # ① 自然排序 + 流复制拼接 + 切点导出
        d = tmp / "clips"
        d.mkdir()
        for name, sec in [("段01.mp4", 0.4), ("段02.mp4", 0.6), ("段10.mp4", 0.8)]:
            make(d / name, sec, "180x320")
        assert [f.name for f in collect(d, "*.mp4")] == ["段01.mp4", "段02.mp4", "段10.mp4"], \
            "自然排序错误（字典序会把段10 排到段02 前）"

        out = tmp / "out" / "成片.mp4"
        cuts_out = tmp / "cuts.txt"
        rc = run(argparse.Namespace(dir=str(d), pattern="*.mp4", out=str(out), apply=True,
                                    reencode_mismatch=False, keep_audio=False,
                                    cuts_out=str(cuts_out)))
        assert rc == 0 and out.exists(), f"拼接未产出 rc={rc}"
        info = probe(out)
        assert 1.7 <= info["dur"] <= 1.95, f"总时长异常 {info['dur']}"
        assert info["w"] == 180 and info["h"] == 320, "成片分辨率异常"
        cuts = [float(x) for x in cuts_out.read_text(encoding="utf-8").split(",")]
        assert len(cuts) == 2, f"切点数异常 {cuts}"
        assert abs(cuts[0] - 0.4) < 0.12 and abs(cuts[1] - 1.0) < 0.15, f"切点异常 {cuts}"

        # ② 异参数：默认拒绝，--reencode-mismatch 后统一到基准
        d2 = tmp / "mixed"
        d2.mkdir()
        make(d2 / "段01.mp4", 0.4, "180x320")
        make(d2 / "段02.mp4", 0.4, "320x180")
        rc = run(argparse.Namespace(dir=str(d2), pattern="*.mp4", out=str(tmp / "m1.mp4"),
                                    apply=True, reencode_mismatch=False, keep_audio=False,
                                    cuts_out=None))
        assert rc == 3, f"异参数未拒绝 rc={rc}"
        out2 = tmp / "m2.mp4"
        rc = run(argparse.Namespace(dir=str(d2), pattern="*.mp4", out=str(out2), apply=True,
                                    reencode_mismatch=True, keep_audio=False, cuts_out=None))
        assert rc == 0 and out2.exists(), f"重编码拼接失败 rc={rc}"
        info2 = probe(out2)
        assert info2["w"] == 180 and info2["h"] == 320, f"重编码未统一到基准 {info2['w']}x{info2['h']}"

        # ③ 输出路径推断：裁切子目录要回溯到工位结构（先裁整拍再拼的常见顺序）
        ep = tmp / "第1集"
        cut = ep / "分镜" / "视频段" / "裁切_5s"
        assert default_out(cut) == ep / "成片" / "第1集_成片.mp4", f"裁切目录推断错 {default_out(cut)}"
        assert default_out(ep / "分镜" / "视频段") == ep / "成片" / "第1集_成片.mp4", "视频段推断错"
        assert default_out(tmp / "随手目录") == tmp / "随手目录" / "成片.mp4", "非工位目录应落本地"

        print("selftest PASS（自然排序 + 切点导出 + 异参数拒绝与重编码统一 + 输出路径推断）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="分镜段拼接成片（默认干跑）")
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--pattern", default="*.mp4")
    ap.add_argument("--out", default=None)
    ap.add_argument("--cuts-out", default=None, help="导出累积切点（逗号分隔秒）")
    ap.add_argument("--keep-audio", action="store_true", help="保留音轨（默认丢弃）")
    ap.add_argument("--reencode-mismatch", action="store_true",
                    help="允许把异参数段重编码到基准参数（有损、较慢）")
    ap.add_argument("--apply", action="store_true", help="执行拼接（默认只干跑）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.dir:
        ap.print_help()
        sys.exit(2)
    sys.exit(run(args))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
