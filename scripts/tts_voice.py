#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配音合成：把台词标注稿按角色拆句，调本地 VoiceStudio 合成 mp3。

配音稿格式（与 references/audio-voice.md 第四节一致）：
    【角色名｜profile_id｜style=xxx】
    纯台词，用 / 做断句分隔/

与 edge-tts 的差别只在 voice 字段：这里填 VoiceStudio 的 profile_id（克隆或
设计出来的音色），不是 zh-CN-XXX 固定音色名。音色表存在 studio.json 的
voices 字段，一次定全剧用。

用法:
    python tts_voice.py 配音稿.txt --out 旁白.mp3
    python tts_voice.py 配音稿.txt --out-dir 第1集/配音
    python tts_voice.py 配音稿.txt --out-dir 第1集/配音 --dry-run
    python tts_voice.py --list-voices
    python tts_voice.py --selftest

退出码: 0=全部合成成功, 1=有段落失败, 2=用法/配置错误

环境变量:
    VOICESTUDIO_URL  服务地址，默认 http://127.0.0.1:3900
    VOICESTUDIO_KEY  API key（本地回环不需要；远程后端才需要）
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:3900"
# 段标签：【角色名｜profile_id｜style=xxx】。profile_id 可省略，此时回落到音色表。
SEG_RE = re.compile(r"^【\s*([^｜|\]】]+?)\s*(?:[｜|]\s*([^｜|\]】]+?)\s*)?(?:[｜|]\s*([^】]+?)\s*)?】\s*$")
# style 值可含空格与逗号（"female, whisper"），取值到下一个 key= 或行尾为止
STYLE_RE = re.compile(r"\bstyle\s*=\s*(.+?)(?=\s+\w+\s*=|$)", re.I)


class CfgError(Exception):
    """配置缺失或不可用（退出码 2）。"""


def parse_script(text):
    """把配音稿拆成段落列表 [{speaker, voice, style, text}]。

    一段只能有一个角色标签（避错五条第 1 条）；标签之外的文字并入上一段。
    """
    segs, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            # 空行=段内大停顿（1.5s），不切段；只有新标签才切
            if cur is not None and cur["text"]:
                cur["text"] += "\n"
            continue
        m = SEG_RE.match(line)
        if m:
            if cur and cur["text"].strip():
                segs.append(cur)
            speaker, voice, rest = m.group(1), m.group(2), m.group(3) or ""
            sm = STYLE_RE.search(rest)
            style = sm.group(1).strip() if sm else None
            cur = {"speaker": speaker.strip(), "voice": (voice or "").strip() or None,
                   "style": style, "text": ""}
        elif cur is not None:
            cur["text"] += ("" if not cur["text"] else "\n") + line
        # 标签之前的散落文字忽略（警示由调用方给出）
    if cur and cur["text"].strip():
        segs.append(cur)
    for s in segs:
        s["text"] = s["text"].strip()
    return segs


def load_voices(project=None):
    """读 studio.json 的 voices 字段：{角色名: {profile_id, style, rate}}。"""
    if not project:
        return {}
    f = Path(project) / "studio.json"
    if not f.is_file():
        return {}
    try:
        cfg = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise CfgError(f"studio.json 无法解析：{e}")
    voices = cfg.get("voices") or {}
    if not isinstance(voices, dict):
        raise CfgError("studio.json 的 voices 必须是 {角色名: {...}} 形式")
    return voices


def resolve(seg, voices):
    """给一段配出 (profile_id, style)。显式标签优先，其次音色表，都没有则报错。"""
    v = voices.get(seg["speaker"]) or {}
    pid = seg["voice"] or v.get("profile_id")
    if not pid:
        raise CfgError(
            f"角色「{seg['speaker']}」没有 profile_id："
            f"在配音稿标签里写【{seg['speaker']}｜profile_id】，"
            f"或在 studio.json 的 voices.{seg['speaker']}.profile_id 配置")
    style = seg["style"] or v.get("style")
    return pid, style


def _request(url, payload=None, key=None, timeout=300):
    """发一个 JSON 请求；payload 为 None 时是 GET。"""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="GET" if data is None else "POST")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def list_voices(base, key=None):
    """GET /v1/audio/voices，返回 [{voice_id, name}]。"""
    raw = _request(f"{base.rstrip('/')}/v1/audio/voices", key=key, timeout=30)
    doc = json.loads(raw.decode("utf-8"))
    return doc.get("voices") or doc.get("data") or []


def synthesize(base, text, voice, style=None, fmt="mp3", key=None, timeout=600):
    """POST /v1/audio/speech，返回音频字节。"""
    payload = {"model": "omnivoice", "input": text, "voice": voice, "response_format": fmt}
    if style:
        # OmniVoice 只认 voice-design 标签（如 female, whisper），散文会被忽略
        payload["instructions"] = style
    url = f"{base.rstrip('/')}/v1/audio/speech"
    try:
        return _request(url, payload, key=key, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise CfgError(f"合成失败 HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise CfgError(
            f"连不上 VoiceStudio（{base}）：{e.reason} "
            f"先启动应用，或用 VOICESTUDIO_URL 指向正确地址")


def safe_name(s):
    """角色名做文件名：去掉路径分隔符与保留字符。"""
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_") or "seg"


def run(args):
    base = args.url or os.environ.get("VOICESTUDIO_URL") or DEFAULT_URL
    key = os.environ.get("VOICESTUDIO_KEY")

    if args.list_voices:
        for v in list_voices(base, key):
            print(f"{v.get('voice_id') or v.get('id')}\t{v.get('name', '')}")
        return 0

    script = Path(args.script)
    if not script.is_file():
        print(f"找不到配音稿：{script}")
        return 2
    voices = load_voices(args.project) if args.project else {}
    segs = parse_script(script.read_text(encoding="utf-8", errors="replace"))
    if not segs:
        print("配音稿里没有可合成的段落（检查【角色｜profile_id】标签）")
        return 2

    try:
        plan = [(s, *resolve(s, voices)) for s in segs]
    except CfgError as e:
        print(f"配置错误：{e}")
        return 2

    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    print(f"服务: {base}")
    print(f"段落: {len(plan)}")
    if args.dry_run:
        for s, pid, style in plan:
            print(f"  [{s['speaker']}] profile={pid} style={style or '-'} "
                  f"chars={len(s['text'])}")
        return 0

    failed = 0
    for i, (s, pid, style) in enumerate(plan, 1):
        if out_dir:
            dst = out_dir / f"{i:03d}_{safe_name(s['speaker'])}.{args.format}"
        elif args.out and len(plan) == 1:
            dst = Path(args.out)
            dst.parent.mkdir(parents=True, exist_ok=True)
        elif args.out:
            p = Path(args.out)
            dst = p.with_name(f"{p.stem}_{i:03d}.{args.format}")
        else:
            print("多个段落时必须给 --out-dir（或 --out 让其自动编号）")
            return 2
        try:
            audio = synthesize(base, s["text"], pid, style, args.format, key)
        except CfgError as e:
            print(f"✗ 第{i}段 [{s['speaker']}] {e}")
            failed += 1
            continue
        dst.write_bytes(audio)
        print(f"✓ {dst}  ({len(s['text'])} 字, {len(audio)} 字节)")
    if failed:
        print(f"\n{failed}/{len(plan)} 段失败")
        return 1
    print(f"\n全部完成：{len(plan)} 段")
    return 0


def selftest():
    # 标签解析：三段、带样式、带省略 profile_id
    src = """【旁白｜p-narr】
他走进雨里。/没有回头。

【主角｜p-lead｜style=female, whisper】
我不走。
"""
    segs = parse_script(src)
    assert len(segs) == 2, segs
    assert segs[0]["speaker"] == "旁白" and segs[0]["voice"] == "p-narr", segs[0]
    assert segs[0]["style"] is None, segs[0]
    assert segs[1]["style"] == "female, whisper", segs[1]
    assert "没有回头" in segs[0]["text"], segs[0]

    # 音色表回落：标签不写 profile_id 时用 studio.json 的配置
    v = {"旁白": {"profile_id": "p-narr", "style": "calm"}}
    pid, style = resolve({"speaker": "旁白", "voice": None, "style": None}, v)
    assert (pid, style) == ("p-narr", "calm"), (pid, style)

    # 显式标签压过音色表
    pid, _ = resolve({"speaker": "旁白", "voice": "p-override", "style": None}, v)
    assert pid == "p-override", pid

    # 缺 profile_id 必须报错，不能静默用默认音色
    try:
        resolve({"speaker": "路人", "voice": None, "style": None}, v)
        raise AssertionError("缺 profile_id 应报错")
    except CfgError:
        pass

    # 文件名净化
    assert safe_name("主/角 A") == "主_角_A", safe_name("主/角 A")
    assert safe_name("///") == "seg", safe_name("///")

    # 段落顺序与空行切分
    segs = parse_script("【甲｜a】\n一\n\n二\n\n【乙｜b】\n三\n")
    assert [s["speaker"] for s in segs] == ["甲", "乙"], segs
    assert len(segs) == 2, segs
    assert "二" in segs[0]["text"], segs[0]

    print("selftest OK")
    return 0


def main():
    ap = argparse.ArgumentParser(description="按角色标注稿调用 VoiceStudio 合成配音")
    ap.add_argument("script", nargs="?", help="配音稿（含【角色｜profile_id】标签）")
    ap.add_argument("--out", help="输出文件（单段，或多段时自动加序号）")
    ap.add_argument("--out-dir", help="输出目录，每段一个文件（推荐）")
    ap.add_argument("--project", help="项目目录（读 studio.json 的 voices 音色表）")
    ap.add_argument("--url", help=f"服务地址，默认 {DEFAULT_URL}")
    ap.add_argument("--format", default="mp3", choices=["mp3", "wav", "flac", "opus", "aac"])
    ap.add_argument("--list-voices", action="store_true", help="列出服务上的可用音色")
    ap.add_argument("--dry-run", action="store_true", help="只打印解析结果，不合成")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.list_voices and not args.script:
        ap.print_help()
        return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
