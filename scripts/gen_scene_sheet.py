# -*- coding: utf-8 -*-
"""场景与资产提示词单生成器（2026-10-20 建）。

数据文件 = 唯一来源：gendata/scenes_<批次>.json
渲染产物默认写当前目录 <标题>.md（md 是 docx 的生成源，不直接交付）

用法：
  python scripts/gen_scene_sheet.py gendata/scenes_1015.json            # 干跑
  python scripts/gen_scene_sheet.py gendata/scenes_1015.json --apply    # 写源稿
  python scripts/gen_scene_sheet.py gendata/scenes_1015.json --verify   # 与现有源稿逐字节比对
  python scripts/gen_scene_sheet.py gendata/scenes_1015.json --docx "<交付目录>" [--force]
  python scripts/gen_scene_sheet.py --selftest

--docx 复用现有 docx 生成链（md2docx → article_style → fix_table_pagination），
输出直接落交付目录，承载根不产生 docx。目标文件已存在时默认中止，先按旧版
归档规则移入 _旧版归档/ 再重跑；--force 允许直接覆盖。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def find_data(name: str) -> Path:
    cands = [Path(name), SCRIPT_DIR / "gendata" / name,
             SCRIPT_DIR / "gendata" / (name + ".json")]
    for c in cands:
        if c.exists():
            return c
    raise SystemExit(f"数据文件不存在：{name}")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def prompt_block(plate: dict) -> str:
    p = plate["prompt"]
    return "\n".join([
        f"> {p['header']}",
        ">",
        f"> 【地理】{p['geography']}",
        ">",
        f"> 【固定锚点】{p['anchors']}",
        ">",
        f"> 【光线】{p['light']}",
        ">",
        f"> 【材质与色彩】{p['material_color']}",
        ">",
        f"> 【排除】{p['exclude']}",
    ])


def render(data: dict) -> str:
    title = data["title"]
    u = data["usage"]
    script = data["script_version"]
    out = []
    out.append(f"# {title}")
    out.append("")
    out.append(data["intro"])
    out.append("")
    out.append("## 1 使用说明")
    out.append("")
    out.append("### 1.1 这份文档解决什么")
    out.append("")
    out.append(u["why"])
    out.append("")
    out.append("### 1.2 与分镜脚本的关系")
    out.append("")
    out.append(u["relation"])
    out.append("")
    out.append("### 1.3 生成与上传流程")
    out.append("")
    out.append(u["flow"])
    out.append("")
    out.append("### 1.4 版本与 state")
    out.append("")
    out.append(u["state_intro"])
    out.append("")
    out.append(u["state_swap"])
    out.append("")
    out.append("## 2 场景板")
    out.append("")
    for i, plate in enumerate(data["plates"], 1):
        out.append(f"### 2.{i} {plate['state']} · {plate['title']}")
        out.append("")
        out.append("| 项目 | 内容 |")
        out.append("| --- | --- |")
        out.append(f"| 用途 | {plate['purpose']} |")
        out.append(f"| 参考 | {plate['reference']} |")
        out.append(f"| 参考用途 | {plate['reference_use']} |")
        out.append(f"| 空场政策 | {plate['empty_policy']} |")
        out.append(f"| 文字政策 | {plate['text_policy_text']} |")
        out.append(f"| 画幅 | {plate['canvas']} |")
        out.append(f"| 锁定句 | {plate['lock_sentence']} |")
        out.append("")
        out.append(plate["ready_note"])
        out.append("")
        out.append("#### 可复制提示词")
        out.append("")
        out.append(prompt_block(plate))
        out.append("")
        out.append("#### 反推来源与核对")
        out.append("")
        out.append(plate["reverse_note"])
        out.append("")
        for k, v in plate["reverse_check"]:
            out.append(f"- {k}：{v}")
        out.append("")
    out.append("## 3 场景图验收清单")
    out.append("")
    out.append("场景图产出后逐项核对，全部通过才可作为全片基准。")
    out.append("")
    for n, item, std in data["acceptance"]:
        out.append(f"{n}. {item}：{std}。")
    out.append("")
    out.append("### 不合格时的处置")
    out.append("")
    out.append("地理或锚点错，重写地理段与锚点段后重生成；光线错，只改光线段；文字错，先改文字政策，仍出现则后期处理，不用更强的负面词硬压。")
    out.append("")
    out.append("## 4 与分镜脚本的对接")
    out.append("")
    h = data["handoff"]
    out.append(h["script_13"])
    out.append("")
    out.append(h["script_17"])
    out.append("")
    out.append(h["state_change"])
    out.append("")
    out.append("## 5 变更记录")
    out.append("")
    for i, (ver, body) in enumerate(data["changes"], 1):
        out.append(f"### 5.{i} {ver}")
        out.append("")
        out.append(body)
        out.append("")
    # 末尾保留一个换行（与源稿一致：最后一行正文 + 换行）
    return "\n".join(out).rstrip("\n") + "\n"


def cmd_render(datafile: Path, apply: bool, verify: bool, out_path: str):
    data = load(datafile)
    text = render(data)
    target = Path(out_path) if out_path else Path.cwd() / f"{data['title']}.md"
    print(f"数据：{datafile}")
    print(f"批次：{data['batch']}  版本：{data['version']}  场景 {len(data['plates'])} 条")
    print(f"渲染：{len(text)} 字符 / {text.count(chr(10))} 行")
    print(f"目标：{target}")
    if verify:
        if not target.exists():
            print("  !! 目标源稿不存在，无法回放比对")
            return 1
        cur = target.read_text(encoding="utf-8")
        if cur == text:
            print("  --verify: 渲染产物与现有源稿逐字节一致 ✓")
            return 0
        import difflib
        diff = list(difflib.unified_diff(cur.splitlines(), text.splitlines(),
                                         fromfile="现有", tofile="渲染", lineterm=""))
        print(f"  !! --verify: 有差异（现有 {len(cur)} 字符 vs 渲染 {len(text)} 字符）")
        for line in diff[:40]:
            print("   ", line)
        return 1
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"  已写出：{target}")
        return 0
    print("  DRY RUN：未写文件（加 --apply 写出，或 --verify 比对现有源稿）")
    return 0


def find_article_scripts(explicit: str):
    """定位 article-format 的 md2docx.py：显式参数 > 环境变量 > 常见技能根。"""
    if explicit:
        return Path(explicit)
    env = os.environ.get("ARTICLE_FORMAT_SCRIPTS", "")
    cands = []
    if env:
        cands.append(Path(env) / "md2docx.py")
    home = Path.home()
    for base in (home / ".zcode" / "skills", home / ".agents" / "skills"):
        cands.append(base / "article-format" / "scripts" / "md2docx.py")
    for c in cands:
        if c.exists():
            return c
    return None


def run_cmd(cmd, env=None):
    r = subprocess.run(cmd, env=env)
    return r.returncode


def cmd_docx(datafile: Path, out_dir: str, force: bool, md2docx: str):
    data = load(datafile)
    text = render(data)
    outdir = Path(out_dir)
    if not outdir.is_dir():
        print(f"交付目录不存在：{outdir}")
        return 2
    target = outdir / f"{data['title']}.docx"
    if target.exists() and not force:
        print(f"目标已存在：{target}")
        print("  按旧版归档规则先移入 _旧版归档/，或加 --force 覆盖。")
        return 2

    md2docx_p = find_article_scripts(md2docx)
    style_p = md2docx_p.parent / "article_style.py"
    if md2docx_p is None or not md2docx_p.exists():
        print("md2docx 不存在：用 --md2docx 指定，或设置 ARTICLE_FORMAT_SCRIPTS 指向 article-format/scripts")
        return 2
    if not style_p.exists():
        print(f"article_style 不存在：{style_p}")
        return 2

    tmpdir = Path(tempfile.mkdtemp(prefix="scenesheet_"))
    try:
        md = tmpdir / f"{data['title']}.md"
        md.write_text(text, encoding="utf-8", newline="\n")
        env = dict(os.environ, ARTICLE_OUT_DIR=str(outdir), PYTHONIOENCODING="gbk")
        base = f"_tmp_{data['title']}.docx"
        print("① md2docx ...")
        if run_cmd([sys.executable, str(md2docx_p), str(md), base], env=env) != 0:
            print("  !! md2docx 失败")
            return 1
        print("② article_style ...")
        if run_cmd([sys.executable, str(style_p), str(outdir / base), str(target)]) != 0:
            print("  !! article_style 失败")
            return 1
        print("③ fix_table_pagination ...")
        if run_cmd([sys.executable, str(SCRIPT_DIR / "fix_table_pagination.py"), str(target)]) != 0:
            print("  !! fix_table_pagination 失败")
            return 1
        print(f"已生成：{target}")
        return 0
    finally:
        (outdir / f"_tmp_{data['title']}.docx").unlink(missing_ok=True)
        shutil.rmtree(tmpdir, ignore_errors=True)


def selftest():
    tmp = Path(tempfile.mkdtemp(prefix="ss_st_"))
    try:
        data = {
            "batch": "测试批", "version": "v1", "date": "2026-01-01",
            "script_version": "v9", "title": "测试场景单",
            "intro": "引言。",
            "usage": {"why": "为什么。", "relation": "关系。", "flow": "流程。",
                      "state_intro": "state 说明。", "state_swap": "换代说明。"},
            "plates": [{
                "id": "S-01", "state": "S-01@day", "view": "", "title": "测试场景",
                "purpose": "底图", "reference": "REF-S01", "reference_use": "地理",
                "empty_policy": "required；空场", "text_policy_source": "no_readable_text",
                "text_policy_render": "blank", "text_policy_text": "blank；无文字",
                "canvas": "9:16", "lock_sentence": "锁定句。",
                "ready_note": "就绪说明。",
                "prompt": {"header": "头部。", "geography": "地理。", "anchors": "锚点一。",
                           "light": "主光自然日光，色温约 6000K，自右后方照入。",
                           "material_color": "无滤镜、无 LUT。", "exclude": "不出现文字。"},
                "reverse_note": "反推说明。",
                "reverse_check": [["地理", "一致"]],
                "spare": False, "delta": ""}],
            "acceptance": [[1, "地理", "通过"]],
            "handoff": {"script_13": "1.3 对接。", "script_17": "1.7 对接。",
                        "state_change": "换 state 顺序。"},
            "changes": [["v1（2026-01-01）", "首版。"]]
        }
        src = tmp / "scenes_test.json"
        src.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        text = render(data)
        assert text.startswith("# 测试场景单\n"), "标题渲染错误"
        assert "### 2.1 S-01@day · 测试场景" in text, "场景板标题渲染错误"
        assert "> 【排除】不出现文字。" in text, "提示词块渲染错误"
        assert "| 8 " not in text, "验收表越界"
        # 回放一致
        out = tmp / "out.md"
        out.write_text(text, encoding="utf-8", newline="\n")
        assert out.read_text(encoding="utf-8") == text
        print("selftest PASS")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
        return
    ap = argparse.ArgumentParser(description="场景与资产提示词单生成器")
    ap.add_argument("data", nargs="?", help="数据文件（gendata/scenes_<批次>.json）")
    ap.add_argument("--apply", action="store_true", help="写源稿")
    ap.add_argument("--verify", action="store_true", help="与现有源稿逐字节比对")
    ap.add_argument("--out", default="", help="指定 md 输出路径")
    ap.add_argument("--docx", default="", help="生成 docx 到指定交付目录")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的 docx")
    ap.add_argument("--md2docx", default="", help="md2docx.py 路径（缺省用 article-format 技能）")
    ap.add_argument("--selftest", action="store_true", help="自检")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.data:
        ap.print_help()
        return
    datafile = find_data(args.data)
    if args.docx:
        sys.exit(cmd_docx(datafile, args.docx, args.force, args.md2docx))
    sys.exit(cmd_render(datafile, args.apply, args.verify, args.out))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
