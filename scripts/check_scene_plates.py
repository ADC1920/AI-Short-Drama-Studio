# -*- coding: utf-8 -*-
"""场景板机检（2026-10-20 建）。

检查对象：场景单数据文件（gendata/scenes_<批次>.json）——数据是唯一来源，
md/docx 由 gen_scene_sheet.py 渲染，机检数据即可覆盖交付内容。

用法：
  python scripts/check_scene_plates.py gendata/scenes_1015.json
  python scripts/check_scene_plates.py <数据> --script "源稿/<分镜脚本>.md"   # 跨文件引用核对
  python scripts/check_scene_plates.py <数据> --ledger "_render/scene_1015/验收底账.md"
  python scripts/check_scene_plates.py --selftest

退出码：0=无阻断项（可有告警）；1=存在阻断项；2=参数/文件错误。
检查项与方案《场景图提示词交付-优化方案-20261020》§5.2 对应；第 12 项（场景图与
场景板视觉一致性）为人工验收，机检只提示，不代判。
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

MAX_PROMPT_CHARS = 4000  # 即梦 Seedance 2.0 Fast 提示词上限
ANCHOR_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}

SENSITIVE_BLOCK_EN = ["chest", "breast", "bust", "torso", "nude", "naked", "bare",
                      "lingerie", "sexy", "cleavage", "nipple", "crotch",
                      "buttocks", "flesh", "underwear"]
SENSITIVE_BLOCK_ZH = ["胸", "裸", "内衣", "性感", "透视"]
SENSITIVE_REVIEW_EN = ["pussy", "corset", "camisole", "chestnut", "blush", "tan"]

EMPTY_POLICIES = {"required", "preferred", "not_required"}
TEXT_SOURCE_POLICIES = {"exact_readable", "graphic_only", "no_readable_text", "pending_creator_text"}
TEXT_RENDER_POLICIES = {"readable", "symbolic", "blank", "postproduction"}
REF_USES = {"地理", "构图", "尺度", "风格", "造型状态"}

EMPTY_PERSON_WORDS = ["模特", "人物", "观众", "人群", "行人", "游客"]
TEXT_READABLE_WORDS = ["可读文字", "清晰文字", "显示文字", "文字内容为", "渲染文字", "写出文字"]
CAMERA_WORDS = ["镜头推近", "镜头拉远", "镜头运动", "运镜", "推镜", "拉镜", "摇镜", "移镜", "跟拍", "环绕"]
MODEL_ACTION_WORDS = ["走秀动作", "步行", "转身", "走上", "走下"]
LIGHT_SOURCE = ["自然日光", "日光", "窗光", "射灯", "洗墙光", "主光", "光源", "阳光"]
LIGHT_DIR = ["自", "方向", "上方", "下方", "左侧", "右侧", "右后", "左后", "前方", "后方", "照入", "投射"]
GEO_DIR = ["左", "右", "前", "后", "上", "下", "中轴", "尽端", "入口", "两侧", "中央"]


def prompt_text(plate):
    p = plate["prompt"]
    order = ["header", "geography", "anchors", "light", "material_color", "exclude"]
    parts = [p.get(k, "") for k in order]
    return "\n".join(parts)


def non_exclude_text(plate):
    p = plate["prompt"]
    return "\n".join([p.get("header", ""), p.get("geography", ""),
                      p.get("anchors", ""), p.get("light", ""),
                      p.get("material_color", "")])


def count_anchors(text):
    hits = re.findall(r"([一二三四五六])是", text)
    if hits:
        return len(hits)
    declared = re.search(r"([一二三四五六])处锚点", text)
    if declared:
        return ANCHOR_NUM[declared.group(1)]
    return len([s for s in re.split(r"[；;]", text) if s.strip()])


def check(data, script_text=None, max_chars=MAX_PROMPT_CHARS):
    """返回 (results, summary)。results=[(level, code, msg)]，level PASS/WARN/FAIL。"""
    res = []

    def add(level, code, msg):
        res.append((level, code, msg))

    plates = data.get("plates") or []
    if not plates:
        add("FAIL", "C0", "场景板为空——至少要有一条 S-* 条目")
        return res

    # C1 必需字段与可复制正文
    required = ["id", "state", "title", "purpose", "reference", "reference_use",
                "empty_policy", "text_policy_text", "canvas", "lock_sentence",
                "prompt", "reverse_check"]
    for i, p in enumerate(plates, 1):
        miss = [k for k in required if not str(p.get(k, "")).strip()]
        if miss:
            add("FAIL", "C1", f"第 {i} 条缺字段：{'、'.join(miss)}")
        pv = prompt_text(p)
        if not pv.strip():
            add("FAIL", "C1", f"{p.get('id', '?')} 可复制提示词为空")
        prompt = p.get("prompt") or {}
        missing_sections = [k for k in ("header", "geography", "anchors", "light",
                                       "material_color", "exclude")
                            if not str(prompt.get(k, "")).strip()]
        if missing_sections:
            add("FAIL", "C1", f"{p.get('id', '?')} 提示词缺分节：{'、'.join(missing_sections)}")

    # C2 ID / state / View
    ids, states = [], []
    for p in plates:
        pid, st = str(p.get("id", "")).strip(), str(p.get("state", "")).strip()
        ids.append(pid)
        states.append(st)
        if not re.fullmatch(r"S-\d{2,}", pid):
            add("FAIL", "C2", f"ID 不合法：{pid!r}（应为 S-01 形式）")
        if not re.fullmatch(r"S-\d{2,}@[a-z0-9][a-z0-9-]*", st):
            add("FAIL", "C2", f"state 不合法：{st!r}（应为 S-01@day-crowd 形式）")
        if st and not st.startswith(pid + "@"):
            add("FAIL", "C2", f"{pid} 的 state 归属错误：{st}")
        view = str(p.get("view", "")).strip()
        if view and not re.fullmatch(rf"{re.escape(pid)}-V\d+", view):
            add("FAIL", "C2", f"View 不合法：{view!r}（应为 {pid}-V1 形式）")
    if len(ids) != len(set(ids)):
        add("FAIL", "C2", "ID 重复：" + "、".join(sorted({x for x in ids if ids.count(x) > 1})))
    if len(states) != len(set(states)):
        add("FAIL", "C2", "state 重复：" + "、".join(sorted({x for x in states if states.count(x) > 1})))

    for p in plates:
        pid = p.get("id", "?")
        pv = prompt_text(p)
        anchors = p["prompt"].get("anchors", "")
        n = count_anchors(anchors)

        # C3 锚点数量与相对关系
        if n < 1:
            add("WARN", "C3", f"{pid} 未识别到固定锚点（1–3 个为宜）")
        elif n > 4:
            add("WARN", "C3", f"{pid} 锚点 {n} 个，超过 4 个易被装饰淹没（建议 1–3）")
        if "相对位置" not in anchors and "相对关系" not in anchors:
            add("WARN", "C3", f"{pid} 锚点段未声明相对关系（如「相对位置不得移动」）")

        # C4 空场政策冲突
        policy = str(p.get("empty_policy", "")).split("；")[0].split(";")[0].strip()
        if policy not in EMPTY_POLICIES:
            add("FAIL", "C4", f"{pid} 空场政策不合法：{policy!r}（required/preferred/not_required）")
        body = non_exclude_text(p)
        hits = [w for w in EMPTY_PERSON_WORDS if w in body]
        if policy == "required" and hits:
            add("FAIL", "C4", f"{pid} 空场政策 required，但正文出现人物词：{'、'.join(hits)}")
        if policy == "preferred" and "模特" in body:
            add("FAIL", "C4", f"{pid} 空场政策 preferred，但正文出现「模特」——T 台上应无人")

        # C5 文字政策冲突
        src = str(p.get("text_policy_source", "")).strip()
        rnd = str(p.get("text_policy_render", "")).strip()
        if src and src not in TEXT_SOURCE_POLICIES:
            add("FAIL", "C5", f"{pid} 文字来源政策不合法：{src!r}")
        if rnd and rnd not in TEXT_RENDER_POLICIES:
            add("FAIL", "C5", f"{pid} 文字呈现政策不合法：{rnd!r}")
        if rnd in {"blank", "postproduction"}:
            hit = [w for w in TEXT_READABLE_WORDS if w in body]
            if hit:
                add("FAIL", "C5", f"{pid} 文字政策 {rnd}，但正文要求可读文字：{'、'.join(hit)}")

        # C6 光线三件套
        light = p["prompt"].get("light", "")
        has_src = any(w in light for w in LIGHT_SOURCE)
        has_dir = any(w in light for w in LIGHT_DIR)
        has_k = bool(re.search(r"\d{3,5}\s*K", light, re.I))
        score = sum([has_src, has_dir, has_k])
        if score < 2:
            add("WARN", "C6", f"{pid} 光线三件套（来源/方向/色温）只齐 {score} 件")

        # C8 写法边界：场景板不写运镜与模特动作
        cam = [w for w in CAMERA_WORDS if w in body]
        if cam:
            add("WARN", "C8", f"{pid} 场景板出现运镜词（应归镜头层）：{'、'.join(cam)}")
        act = [w for w in MODEL_ACTION_WORDS if w in body]
        if act:
            add("WARN", "C8", f"{pid} 场景板出现模特动作词：{'、'.join(act)}")

        # C9 字数与占位符
        nchar = len(pv)
        if nchar > max_chars:
            add("FAIL", "C9", f"{pid} 提示词 {nchar} 字符，超过 {max_chars}")
        if re.search(r"\{\{[^{}]+\}\}", pv):
            add("FAIL", "C9", f"{pid} 存在未填占位符")

        # C10 敏感词
        low = pv.lower()
        block = [w for w in SENSITIVE_BLOCK_EN if w in low] + [w for w in SENSITIVE_BLOCK_ZH if w in pv]
        if block:
            add("FAIL", "C10", f"{pid} 命中必拦敏感词：{'、'.join(block)}")
        review = [w for w in SENSITIVE_REVIEW_EN if re.search(r"\b" + re.escape(w) + r"\b", low)]
        if review:
            add("WARN", "C10", f"{pid} 命中复核词（人工判读）：{'、'.join(review)}")

        # C11 地理可读性
        geo = p["prompt"].get("geography", "")
        if geo and not any(w in geo for w in GEO_DIR):
            add("WARN", "C11", f"{pid} 地理段缺方向词，读者无法还原空间关系")
        if geo and not re.search(r"(观察机位|视线|视角|镜头位于)", geo):
            add("WARN", "C11", f"{pid} 地理段缺观察点（「从…看」句式）")

        # C5b 参考用途只能是五选一
        ref_use = str(p.get("reference_use", ""))
        head = ref_use.split("；")[0].split(";")[0].strip()
        if head and head not in REF_USES:
            add("WARN", "C5b", f"{pid} 参考用途首项 {head!r} 不在五选一之列（地理/构图/尺度/风格/造型状态）")

    # C7 同 Location 同 state 的 View 光线一致性
    groups = {}
    for p in plates:
        groups.setdefault((p.get("id"), p.get("state")), []).append(p)
    for (pid, st), group in groups.items():
        if len(group) < 2:
            continue
        lights = [g["prompt"].get("light", "") for g in group]
        ks = {tuple(re.findall(r"\d{3,5}\s*K", x, re.I)) for x in lights}
        dirs = {tuple(sorted({w for w in LIGHT_DIR if w in x})) for x in lights}
        if len(ks) > 1 or len(dirs) > 1:
            add("FAIL", "C7", f"{pid} {st} 的多条 View 光线口径不一致，需写 delta 并说明成因")

    # C8b 跨文件引用
    if script_text is not None:
        refs = set(re.findall(r"S-\d{2,}(?:@[a-z0-9][a-z0-9-]*)?", script_text))
        known = set()
        for p in plates:
            known.add(p["id"])
            known.add(p["state"])
        unknown = sorted(r for r in refs if r not in known and r.split("@")[0] not in {p["id"] for p in plates})
        if unknown:
            add("FAIL", "C8b", "分镜脚本引用了场景单中不存在的编号：" + "、".join(unknown))
        if not refs:
            add("FAIL", "C8b", "分镜脚本未出现任何 S-* 引用——尚未接入场景单（v22 待做）")
        for p in plates:
            used = any(r == p["state"] or r == p["id"] for r in refs)
            if not used and not p.get("spare"):
                add("FAIL", "C8b", f"{p['state']} 未被任何镜头引用，也未标「备用」")
            if p.get("spare"):
                add("PASS", "C8b", f"{p['state']} 标记为备用，允许未引用")
        if p.get("lock_sentence") and p["lock_sentence"] not in script_text:
            add("WARN", "C8b", f"{p['state']} 锁定句未在分镜脚本中原样出现")
    else:
        add("PASS", "C8b", "未提供 --script，跨文件引用核对跳过")

    # C12 视觉一致性：人工验收
    add("WARN", "C12", "场景图与场景板的视觉一致性为人工验收项，机检不代判")

    fails = sum(1 for lv, _, _ in res if lv == "FAIL")
    warns = sum(1 for lv, _, _ in res if lv == "WARN")
    summary = {"plates": len(plates), "pass": sum(1 for lv, _, _ in res if lv == "PASS"),
               "warn": warns, "fail": fails}
    return res, summary


def format_report(datafile, res, summary):
    lines = [f"场景板机检：{datafile}",
             f"条目 {summary['plates']} 条｜PASS {summary['pass']}｜WARN {summary['warn']}｜FAIL {summary['fail']}",
             ""]
    for lv, code, msg in res:
        lines.append(f"[{lv}] {code} {msg}")
    return "\n".join(lines)


def selftest():
    tmp = Path(tempfile.mkdtemp(prefix="sp_st_"))
    try:
        def plate(**kw):
            base = {
                "id": "S-01", "state": "S-01@day", "view": "", "title": "测试",
                "purpose": "底图", "reference": "REF-S01", "reference_use": "地理；控制布局",
                "empty_policy": "required；绝对无人", "text_policy_source": "no_readable_text",
                "text_policy_render": "blank", "text_policy_text": "blank；无文字",
                "canvas": "9:16", "lock_sentence": "锁定句。",
                "prompt": {"header": "空镜。", "geography": "观察机位在中轴，视线看向尽端。",
                           "anchors": "一是背景板；二是灯架。锚点的相对位置不得移动。",
                           "light": "主光为自然日光，色温约 6000K，自右后方照入。",
                           "material_color": "无滤镜、无 LUT。", "exclude": "不出现文字。"},
                "reverse_check": [["地理", "一致"]], "spare": False,
            }
            base.update(kw)
            return base

        data = {"plates": [plate()]}
        res, s = check(data)
        assert s["fail"] == 0, f"合规样例不应 FAIL：{res}"

        # 空场冲突
        bad = plate(empty_policy="required；绝对无人")
        bad["prompt"]["geography"] = "观众坐在两侧。"
        _, s = check({"plates": [bad]})
        assert s["fail"] >= 1, "空场冲突未拦截"

        # 文字政策冲突
        bad2 = plate(text_policy_render="blank")
        bad2["prompt"]["geography"] = "画面中有可读文字。"
        _, s = check({"plates": [bad2]})
        assert s["fail"] >= 1, "文字政策冲突未拦截"

        # ID 重复
        _, s = check({"plates": [plate(), plate()]})
        assert s["fail"] >= 1, "ID 重复未拦截"

        # 跨文件：脚本无 S-*
        _, s = check({"plates": [plate()]}, script_text="全部镜头用场景图.jpg")
        assert s["fail"] >= 1, "脚本未接入场景单未拦截"
        # 跨文件：正常引用
        _, s = check({"plates": [plate()]}, script_text="场景 S-01@day，锁定句。")
        assert s["fail"] == 0, f"正常引用不应 FAIL：{s}"

        # 字数超限
        big = plate()
        big["prompt"]["geography"] = "很长" * 2500
        _, s = check({"plates": [big]})
        assert s["fail"] >= 1, "超长未拦截"

        print("selftest PASS")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="场景板机检")
    ap.add_argument("data", nargs="?", help="场景单数据文件")
    ap.add_argument("--script", default="", help="分镜脚本 md（跨文件引用核对）")
    ap.add_argument("--ledger", default="", help="底账 Markdown 输出路径")
    ap.add_argument("--max-chars", type=int, default=MAX_PROMPT_CHARS, help="单条提示词字符上限（默认 4000）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--selftest", action="store_true", help="自检")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.data:
        ap.print_help()
        return
    p = Path(args.data)
    if not p.exists():
        print(f"数据文件不存在：{p}")
        return 2
    data = json.loads(p.read_text(encoding="utf-8"))
    script_text = None
    if args.script:
        sp = Path(args.script)
        if not sp.exists():
            print(f"分镜脚本不存在：{sp}")
            return 2
        script_text = sp.read_text(encoding="utf-8")
    res, summary = check(data, script_text, args.max_chars)
    if args.json:
        print(json.dumps({"summary": summary,
                          "results": [{"level": lv, "code": c, "msg": m} for lv, c, m in res]},
                         ensure_ascii=False, indent=1))
    else:
        print(format_report(p, res, summary))
    if args.ledger:
        lp = Path(args.ledger)
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(format_report(p, res, summary) + "\n", encoding="utf-8", newline="\n")
        print(f"\n底账已写出：{lp}")
    return 1 if summary["fail"] else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
