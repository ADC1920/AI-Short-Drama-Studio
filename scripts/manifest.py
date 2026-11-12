# -*- coding: utf-8 -*-
"""分镜生成清单（manifest）工具（2026-10-17 建）。

用途：记录每段分镜视频的生成信息（提示词版本、参考图、定稿/候选状态），
供验收前核对「相邻两段是否同源」——混源批次是接缝跳跃的常见结构性来源。

数据文件：<分镜目录>/_manifest.json

用法：
  python scripts/manifest.py init <分镜目录> --batch demo [--script-version v1] [--scene-state S-01@day-crowd] [--force]
  python scripts/manifest.py set  <分镜目录> --shot "LOOK 01" --status 定稿 --script-version v1 --scene-state S-01@day-crowd
  python scripts/manifest.py list <分镜目录>
  python scripts/manifest.py verify <分镜目录> [--expect-version v21] [--expect-scene S-01@day-crowd]
  python scripts/manifest.py selftest

约定：
  - 只维护元数据，不动视频文件；--status: 定稿/候选/待核（默认 待核）。
  - verify 检查：①同一提示词版本（或与 --expect-version 一致）②状态是否齐为定稿
    ③文件是否仍在目录中 ④场景 state 是否全片一致（混用两版场景即混源）
    ⑤提示词内容哈希是否一致（防止改了提示词忘升版号造成假绿）；
    输出不一致清单（退出码 1＝有问题）。
  - script_version 是人手填的标签，不绑定提示词正文；prompt_sha256 才是内容指纹。
    老清单无该字段时降级为警告，不阻断（--strict-hash 可升级为错误）。
"""
import argparse
import hashlib
import json
import re
import sys
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

MANIFEST_NAME = "_manifest.json"


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_prompt(text: str) -> str:
    """提示词规范化，哈希口径的唯一入口。

    去首尾空白、内部连续空白压成单空格、换行统一 \\n、不做大小写变换
    （中文无大小写，英文大小写有语义）。
    改本函数等于改变哈希口径——历史清单的 prompt_sha256 会全部失效，需配迁移脚本。
    """
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t\f\v]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def prompt_hash(text: str) -> str:
    """提示词正文的 sha256 前 12 位。"""
    return hashlib.sha256(normalize_prompt(text).encode("utf-8")).hexdigest()[:12]


def load_dir(d: Path):
    mf = d / MANIFEST_NAME
    if not mf.exists():
        print(f"未找到清单 {mf}（先跑 init）")
        sys.exit(2)
    return mf, json.loads(mf.read_text(encoding="utf-8"))


def save(mf: Path, data: dict):
    data["updated"] = now()
    mf.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                  encoding="utf-8", newline="\n")


def scan(d: Path, pattern: str):
    files = sorted([p for p in d.glob(pattern) if p.is_file()])
    # 开场排最前（"LOOK  0" 字符串序本就在前，此处再兜底）
    files.sort(key=lambda p: (0 if "0" in p.stem[:8] and "开场" in p.stem else 1, p.name))
    return files


def cmd_init(args):
    d = Path(args.dir)
    mf = d / MANIFEST_NAME
    if mf.exists() and not args.force:
        print(f"清单已存在：{mf}（要重建加 --force）")
        sys.exit(2)
    ph = prompt_hash(args.prompt) if args.prompt else ""
    shots = []
    for i, p in enumerate(scan(d, args.pattern), 1):
        shots.append({
            "order": i,
            "shot": p.stem,
            "file": p.name,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            "script_version": args.script_version or "",
            "scene_state": args.scene_state or "",
            "refs": [],
            "prompt_sha256": ph,
            "prompt_source": args.prompt_source or "",
            "status": "待核",
            "note": "",
        })
    data = {"batch": args.batch or "", "script_version": args.script_version or "",
            "scene_state": args.scene_state or "",
            "prompt_sha256": prompt_hash(args.prompt) if args.prompt else "",
            "updated": now(), "shots": shots}
    save(mf, data)
    print(f"已建清单：{mf}（{len(shots)} 段）")
    if args.prompt:
        print(f"提示词哈希：{data['prompt_sha256']}（来源 {args.prompt_source or '未标注'}）")


def find_shot(data, key: str):
    for s in data["shots"]:
        if s["shot"] == key or s["file"] == key or s["shot"].startswith(key):
            return s
    return None


def cmd_set(args):
    mf, data = load_dir(Path(args.dir))
    s = find_shot(data, args.shot)
    if not s:
        print(f"未找到：{args.shot}（可用 list 查看）")
        sys.exit(2)
    for k, v in [("script_version", args.script_version), ("status", args.status),
                 ("note", args.note), ("scene_state", args.scene_state),
                 ("prompt_source", args.prompt_source)]:
        if v is not None:
            s[k] = v
    if args.prompt is not None:
        s["prompt_sha256"] = prompt_hash(args.prompt)
    if args.refs is not None:
        s["refs"] = [x for x in args.refs.split(";") if x]
    save(mf, data)
    print(f"已更新 {s['shot']}：version={s['script_version']} scene={s.get('scene_state','') or '-'} status={s['status']}")


def cmd_list(args):
    _, data = load_dir(Path(args.dir))
    print(f"批次 {data.get('batch','')}  脚本版本 {data.get('script_version','')}  更新 {data.get('updated','')}")
    for s in data["shots"]:
        print(f"  {s['order']:>2}  {s['shot']:<24} {s['status']:<4} v={s['script_version'] or '-':<6} scene={s.get('scene_state','') or '-':<16} {s['mtime']}  refs={len(s['refs'])}")


def cmd_verify(args):
    d = Path(args.dir)
    mf, data = load_dir(d)
    expect = args.expect_version or data.get("script_version") or ""
    expect_scene = args.expect_scene or data.get("scene_state") or ""
    issues, warns = [], []
    versions, scenes, hashes = {}, {}, {}
    for s in data["shots"]:
        fp = d / s["file"]
        if not fp.exists():
            issues.append(f"文件缺失：{s['shot']} → {s['file']}")
        v = s["script_version"] or "(未记)"
        versions.setdefault(v, []).append(s["shot"])
        if s["status"] != "定稿":
            issues.append(f"非定稿：{s['shot']}（{s['status']}）")
        if expect and v != expect:
            issues.append(f"版本不符：{s['shot']} 记 {v}，期望 {expect}")
        ss = s.get("scene_state") or "(未记)"
        scenes.setdefault(ss, []).append(s["shot"])
        if expect_scene and ss != expect_scene:
            issues.append(f"场景版本不符：{s['shot']} 记 {ss}，期望 {expect_scene}")
        # 提示词内容指纹：版号是人填标签，哈希才是内容；版号相同但哈希不同＝同名不同内容
        h = s.get("prompt_sha256") or ""
        if h:
            hashes.setdefault(h, []).append(s["shot"])
    print(f"清单 {mf}  批次 {data.get('batch','')}  共 {len(data['shots'])} 段")
    print("版本分布：" + "；".join(f"{v}×{len(vs)}" for v, vs in versions.items()))
    print("场景 state 分布：" + "；".join(f"{v}×{len(vs)}" for v, vs in scenes.items()))
    if len(scenes) > 1:
        issues.append("场景 state 不一致（混用两版场景即混源）：" +
                      "；".join(f"{v}×{len(vs)}" for v, vs in scenes.items()))

    # 哈希核对
    no_hash = [s["shot"] for s in data["shots"] if not (s.get("prompt_sha256") or "")]
    if len(hashes) > 1:
        detail = "；".join(f"{h}×{len(vs)}" for h, vs in hashes.items())
        issues.append(f"提示词内容不一致（同名不同内容，版号相同但正文已改）：{detail}")
    elif hashes:
        print("提示词哈希分布：" + "；".join(f"{h}×{len(vs)}" for h, vs in hashes.items()))
    if args.expect_prompt_sha:
        for h, vs in hashes.items():
            if h != args.expect_prompt_sha:
                issues.append(f"提示词哈希不符：{h}（{len(vs)} 段）期望 {args.expect_prompt_sha}")
    if no_hash:
        msg = f"未记提示词哈希（{len(no_hash)} 段），无法验证内容同源：" + "、".join(no_hash[:5])
        if args.strict_hash:
            issues.append(msg + "（--strict-hash）")
        else:
            warns.append(msg)

    if warns:
        print("\n警告：" + str(len(warns)) + " 项——")
        for w in warns:
            print("  -", w)
    if issues:
        print(f"\n同源核对：{len(issues)} 项待处理——")
        for it in issues:
            print("  -", it)
        sys.exit(1)
    print("\n同源核对：通过（全部定稿、版本一致、场景 state 一致、文件在位"
          + ("、提示词内容一致" if hashes else "") + "）")


def cmd_backfill(args):
    """从分镜 JSON 抽每镜提示词，回填 prompt_sha256——存量项目补哈希用。"""
    mf, data = load_dir(Path(args.dir))
    sb = Path(args.backfill_hash)
    if not sb.is_file():
        print(f"分镜 JSON 不存在：{sb}")
        sys.exit(2)
    try:
        payload = json.loads(sb.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"分镜 JSON 解析失败：{e}")
        sys.exit(2)
    shots = payload.get("shots") if isinstance(payload, dict) else None
    if not isinstance(shots, list):
        print("分镜 JSON 无 shots 数组")
        sys.exit(2)
    # 建镜号 → 提示词映射；镜号取 shot_number / shot，字段名各版本不一
    by_key = {}
    for sh in shots:
        if not isinstance(sh, dict):
            continue
        key = str(sh.get("shot_number") or sh.get("shot") or "").strip()
        text = sh.get("prompt_text") or sh.get("prompt") or ""
        if key and text:
            by_key[key] = text
    filled, missing = 0, []
    for s in data["shots"]:
        text = by_key.get(s["shot"]) or by_key.get(str(s["order"]))
        if text:
            s["prompt_sha256"] = prompt_hash(text)
            s["prompt_source"] = str(args.backfill_hash)
            filled += 1
        else:
            missing.append(s["shot"])
    save(mf, data)
    print(f"已回填 {filled} 段提示词哈希（来源 {sb}）")
    if missing:
        print(f"未匹配到提示词 {len(missing)} 段：" + "、".join(missing[:8]))
        print("提示：确认分镜 JSON 里的 shot_number 与清单 shot 名能对上，或改用 set --prompt 逐段填")
    print("下一步：重跑 verify 复核")


def selftest():
    tmp = Path(tempfile.mkdtemp(prefix="mf_st_"))
    try:
        for n in ["LOOK  0 · 开场.mp4", "LOOK 01 · 甲.mp4", "LOOK 02 · 乙.mp4"]:
            (tmp / n).write_bytes(b"stub")
        ns = argparse.Namespace(dir=str(tmp), pattern="*.mp4", batch="test",
                                script_version="v21", scene_state="S-01@day-crowd",
                                prompt="", prompt_source="", force=False)
        cmd_init(ns)
        _, data = load_dir(tmp)
        assert len(data["shots"]) == 3 and data["shots"][0]["shot"].startswith("LOOK  0"), "初始化排序错误"
        assert data["scene_state"] == "S-01@day-crowd", "场景 state 未写入"
        ns2 = argparse.Namespace(dir=str(tmp), shot="LOOK 01", script_version=None,
                                 status="定稿", note="优选第 2 次", refs="a.jpg;b.jpg",
                                 scene_state=None, prompt=None, prompt_source=None)
        cmd_set(ns2)
        _, data = load_dir(tmp)
        s = find_shot(data, "LOOK 01")
        assert s["status"] == "定稿" and s["refs"] == ["a.jpg", "b.jpg"], "set 未生效"
        # verify 应因未全定稿而失败（exit 1）
        import contextlib, io
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                cmd_verify(argparse.Namespace(dir=str(tmp), expect_version="v21",
                                              expect_scene="", expect_prompt_sha="",
                                              strict_hash=False))
            raise AssertionError("verify 应报 2 项非定稿")
        except SystemExit as e:
            assert e.code == 1, f"verify 退出码应为 1，实际 {e.code}"
        # 全部定稿 + 同一场景 state → 应通过
        for name in ["LOOK  0 · 开场", "LOOK 02 · 乙"]:
            cmd_set(argparse.Namespace(dir=str(tmp), shot=name, script_version=None,
                                      status="定稿", note=None, refs=None,
                                      scene_state=None, prompt=None, prompt_source=None))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_verify(argparse.Namespace(dir=str(tmp), expect_version="v21",
                                          expect_scene="S-01@day-crowd",
                                          expect_prompt_sha="", strict_hash=False))
        assert "通过" in buf.getvalue(), "同源清单应通过"
        # 混入另一版场景 → 应失败
        cmd_set(argparse.Namespace(dir=str(tmp), shot="LOOK 02", script_version=None,
                                   status=None, note=None, refs=None,
                                   scene_state="S-01@night-empty",
                                   prompt=None, prompt_source=None))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                cmd_verify(argparse.Namespace(dir=str(tmp), expect_version="v21",
                                              expect_scene="", expect_prompt_sha="",
                                              strict_hash=False))
            raise AssertionError("verify 应报场景 state 不一致")
        except SystemExit as e:
            assert e.code == 1, f"场景不一致退出码应为 1，实际 {e.code}"
        assert "场景 state 不一致" in buf.getvalue(), "未输出场景不一致清单"

        # === 提示词哈希用例 ===
        # 规范化：同一提示词的不同空白形态必须算出同一哈希
        a = prompt_hash("  中景，@顾寒 站在门口。\n\n  冷调侧光。  ")
        b = prompt_hash("中景，@阿青 站在门口。\r\n冷调侧光。")
        c = prompt_hash("中景，@阿青 站在门口。\n冷调侧光。")
        assert b == c, f"空白形态不同应同哈希：{b} != {c}"
        assert a != c, "主体不同应不同哈希"
        assert len(c) == 12, f"哈希应 12 位，实际 {len(c)}"

        # 同名不同内容：版号相同但提示词已改 → verify 必须报错
        for name in ["LOOK  0 · 开场", "LOOK 01", "LOOK 02"]:
            cmd_set(argparse.Namespace(dir=str(tmp), shot=name, script_version=None,
                                      status=None, note=None, refs=None,
                                      scene_state=None, prompt="原始提示词",
                                      prompt_source="sb.json"))
        cmd_set(argparse.Namespace(dir=str(tmp), shot="LOOK 02", script_version=None,
                                   status=None, note=None, refs=None,
                                   scene_state=None, prompt="改过的提示词",
                                   prompt_source="sb.json"))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                cmd_verify(argparse.Namespace(dir=str(tmp), expect_version="v21",
                                              expect_scene="", expect_prompt_sha="",
                                              strict_hash=False))
            raise AssertionError("版号相同但提示词不同，verify 应失败")
        except SystemExit as e:
            assert e.code == 1
        assert "同名不同内容" in buf.getvalue(), buf.getvalue()

        # 老清单无哈希 → 降级为警告，不阻断
        tmp2 = Path(tempfile.mkdtemp(prefix="mf_st2_"))
        try:
            for n in ["LOOK 01.mp4"]:
                (tmp2 / n).write_bytes(b"stub")
            cmd_init(argparse.Namespace(dir=str(tmp2), pattern="*.mp4", batch="old",
                                       script_version="v1", scene_state="",
                                       prompt="", prompt_source="", force=False))
            cmd_set(argparse.Namespace(dir=str(tmp2), shot="LOOK 01", script_version=None,
                                      status="定稿", note=None, refs=None,
                                      scene_state=None, prompt=None, prompt_source=None))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_verify(argparse.Namespace(dir=str(tmp2), expect_version="v1",
                                              expect_scene="", expect_prompt_sha="",
                                              strict_hash=False))
            assert "通过" in buf.getvalue(), "无哈希的老清单应通过"
            assert "未记提示词哈希" in buf.getvalue(), "应给哈希缺失警告"
            # strict 升级为错误
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    cmd_verify(argparse.Namespace(dir=str(tmp2), expect_version="v1",
                                                  expect_scene="", expect_prompt_sha="",
                                                  strict_hash=True))
                raise AssertionError("--strict-hash 应让无哈希成为错误")
            except SystemExit as e:
                assert e.code == 1
            # 回填后应通过且带哈希
            sb = tmp2 / "sb.json"
            sb.write_text(json.dumps({"shots": [{"shot_number": "LOOK 01",
                                                 "prompt_text": "中景，人物入画。"}]},
                                     ensure_ascii=False), encoding="utf-8")
            cmd_backfill(argparse.Namespace(dir=str(tmp2), backfill_hash=str(sb)))
            _, d2 = load_dir(tmp2)
            assert d2["shots"][0]["prompt_sha256"], "回填未写入哈希"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_verify(argparse.Namespace(dir=str(tmp2), expect_version="v1",
                                              expect_scene="", expect_prompt_sha="",
                                              strict_hash=True))
            assert "通过" in buf.getvalue(), "回填后 strict 应通过"
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)
        print("selftest PASS（含提示词哈希：规范化/同名不同内容/老清单降级/strict/回填）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
        return
    ap = argparse.ArgumentParser(description="分镜生成清单（manifest）工具")
    sub = ap.add_subparsers(dest="cmd")
    p1 = sub.add_parser("init", help="扫描目录建清单")
    p1.add_argument("dir"); p1.add_argument("--pattern", default="*.mp4")
    p1.add_argument("--batch", default=""); p1.add_argument("--script-version", default="")
    p1.add_argument("--scene-state", default="", help="场景单 state（如 S-01@day-crowd）")
    p1.add_argument("--prompt", default="", help="提示词正文（算出 prompt_sha256 写入）")
    p1.add_argument("--prompt-source", default="", help="提示词来源路径，如 分镜/sb.json#组01")
    p1.add_argument("--force", action="store_true")
    p2 = sub.add_parser("set", help="更新条目")
    p2.add_argument("dir"); p2.add_argument("--shot", required=True)
    p2.add_argument("--script-version"); p2.add_argument("--status"); p2.add_argument("--note")
    p2.add_argument("--scene-state", help="该镜使用的场景 state")
    p2.add_argument("--refs", help="分号分隔的参考图清单")
    p2.add_argument("--prompt", help="提示词正文（算出 prompt_sha256 写入）")
    p2.add_argument("--prompt-source", help="提示词来源路径")
    p3 = sub.add_parser("list", help="列出清单"); p3.add_argument("dir")
    p4 = sub.add_parser("verify", help="同源核对")
    p4.add_argument("dir"); p4.add_argument("--expect-version", default="")
    p4.add_argument("--expect-scene", default="", help="期望的场景 state")
    p4.add_argument("--expect-prompt-sha", default="", help="期望的提示词哈希")
    p4.add_argument("--strict-hash", action="store_true",
                    help="无哈希升级为错误（已全量回填的项目用）")
    p6 = sub.add_parser("backfill-hash", help="从分镜 JSON 回填提示词哈希")
    p6.add_argument("dir"); p6.add_argument("--backfill-hash", required=True,
                                            help="分镜 JSON 路径")
    p5 = sub.add_parser("selftest", help="自检")
    args = ap.parse_args()
    if args.cmd == "init":
        cmd_init(args)
    elif args.cmd == "set":
        cmd_set(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "verify":
        cmd_verify(args)
    elif args.cmd == "backfill-hash":
        cmd_backfill(args)
    elif args.cmd == "selftest":
        selftest()
    else:
        ap.print_help()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
