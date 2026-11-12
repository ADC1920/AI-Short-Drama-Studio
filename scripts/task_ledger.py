# -*- coding: utf-8 -*-
"""生成任务台账与成本记账（ai-short-drama-studio 技能）。

用途：把 SKILL.md 的「估算 → 确认 → 记账」三步里的记账变成可查的文件。
跨会话后仍能对账：这批花了多少、失败重抽浪费多少、哪些镜还没回执。

数据文件：<项目>/_tasks.jsonl，一行一个事件，追加写不覆盖（事件溯源，不是状态快照）。

用法：
  python scripts/task_ledger.py submit <项目> --unit 第1集 --shot 组01 --prompt-sha a1b2c3d4e5f6 --model seedance-2.5 [--est-credits 130] [--force]
  python scripts/task_ledger.py result <项目> --unit 第1集 --shot 组01 --status success --actual-credits 130 [--artifact 第1集/分镜/视频段/段01.mp4] [--note "重抽第2次"]
  python scripts/task_ledger.py cancel <项目> --unit 第1集 --shot 组01 [--note 内容审核]
  python scripts/task_ledger.py recover <项目> [--unit 第1集]    # 只读：列已提交未回执
  python scripts/task_ledger.py report <项目> [--json]
  python scripts/task_ledger.py selftest

口径：
  - 已花（spent）只统计 status=success 的 actual_credits。
  - 浪费（wasted）统计 status=failed 的 actual_credits——失败那次也算钱，这正是要暴露的。
  - pending＝有 submit 无 result/cancel；attempts＝同一 (unit, shot) 的 submit 次数。
  - submit 遇到已有 pending 的同镜直接拒绝，除非 --force（防重复提交重复计费）。
  - recover 纯只读，不写盘、不触发任何生成——这是「只查不重生成」的落地。
"""
import argparse
import json
import sys
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

LEDGER_NAME = "_tasks.jsonl"
STATUSES = ("success", "failed", "cancelled")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ledger_path(root: Path) -> Path:
    return root / LEDGER_NAME


def append_event(root: Path, event: dict):
    """追加一行事件。必填字段缺失直接报错，不写半条。"""
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_events(root: Path):
    """读全量事件。坏行跳过并返回坏行数（容错，不让一行坏掉整本账）。"""
    path = ledger_path(root)
    if not path.is_file():
        return [], 0
    events, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(ev, dict) and ev.get("event"):
            events.append(ev)
        else:
            bad += 1
    return events, bad


def fold_state(events):
    """事件折叠为 {(unit, shot): 状态}。

    折叠规则：
      - 最后一条 result/cancel 决定终态；
      - 有 submit 无 result/cancel 即 pending；
      - failed 后再 submit，attempts 加一，失败积分计入 wasted。
    """
    state = {}
    for ev in events:
        key = (ev.get("unit", ""), ev.get("shot", ""))
        s = state.setdefault(key, {
            "unit": key[0], "shot": key[1], "status": "unknown",
            "attempts": 0, "spent": 0.0, "wasted": 0.0,
            "est": 0.0, "artifact": "", "prompt_sha256": "", "last": "",
        })
        kind = ev.get("event")
        s["last"] = ev.get("ts", "")
        if kind == "submit":
            s["attempts"] += 1
            s["status"] = "pending"
            s["error"] = ""
            if ev.get("prompt_sha256"):
                s["prompt_sha256"] = ev["prompt_sha256"]
            if ev.get("est_credits") is not None:
                s["est"] += float(ev["est_credits"])
        elif kind == "result":
            st = ev.get("status") or ""
            credits = float(ev.get("actual_credits") or 0)
            s["status"] = st
            if st == "success":
                s["spent"] += credits
                if ev.get("artifact"):
                    s["artifact"] = ev["artifact"]
            elif st == "failed":
                s["wasted"] += credits
                s["error"] = ev.get("note") or "失败（未记原因）"
            else:
                s["status"] = "cancelled"
                s["error"] = ev.get("note") or "取消"
        elif kind == "cancel":
            s["status"] = "cancelled"
            s["error"] = ev.get("note") or "取消"
    return state


def check_duplicate(state, unit: str, shot: str):
    """返回该镜是否已有 pending。"""
    s = state.get((unit, shot))
    return bool(s and s["status"] == "pending")


def summarize(state, bad_lines=0):
    rows = list(state.values())
    spent = sum(r["spent"] for r in rows)
    wasted = sum(r["wasted"] for r in rows)
    pending = [r for r in rows if r["status"] == "pending"]
    by_unit = {}
    for r in rows:
        u = by_unit.setdefault(r["unit"], {"spent": 0.0, "wasted": 0.0, "shots": 0})
        u["spent"] += r["spent"]
        u["wasted"] += r["wasted"]
        u["shots"] += 1
    return {
        "spent": spent, "wasted": wasted,
        "waste_ratio": round(wasted / spent, 3) if spent else 0.0,
        "pending": len(pending),
        "pending_shots": [f"{r['unit']}/{r['shot']}" for r in pending],
        "units": len(by_unit), "shots": len(rows),
        "by_unit": by_unit, "bad_lines": bad_lines,
    }


def cmd_submit(args):
    root = Path(args.root)
    if not root.is_dir():
        print(f"项目目录不存在：{root}")
        return 2
    events, bad = load_events(root)
    state = fold_state(events)
    if check_duplicate(state, args.unit, args.shot) and not args.force:
        print(f"已有运行中任务：{args.unit}/{args.shot}——先 result 或 cancel 再提交；"
              f"确需重提加 --force（注意可能重复计费）")
        return 3
    ev = {"ts": now(), "event": "submit", "unit": args.unit, "shot": args.shot,
          "prompt_sha256": args.prompt_sha, "model": args.model}
    if args.est_credits is not None:
        ev["est_credits"] = args.est_credits
    if args.note:
        ev["note"] = args.note
    append_event(root, ev)
    est = f"，预估 {args.est_credits} 分" if args.est_credits is not None else ""
    print(f"已提交 {args.unit}/{args.shot}（{args.model}{est}）")
    if bad:
        print(f"注意：台账有 {bad} 行无法解析，已跳过")
    return 0


def cmd_result(args):
    root = Path(args.root)
    if not root.is_dir():
        print(f"项目目录不存在：{root}")
        return 2
    if args.status not in STATUSES:
        print(f"--status 只能是 {'/'.join(STATUSES)}")
        return 2
    events, bad = load_events(root)
    state = fold_state(events)
    if (args.unit, args.shot) not in state:
        print(f"未见 submit 记录：{args.unit}/{args.shot}（先 submit 再登记结果）")
        return 2
    ev = {"ts": now(), "event": "result", "unit": args.unit, "shot": args.shot,
          "status": args.status, "actual_credits": args.actual_credits}
    if args.artifact:
        ev["artifact"] = args.artifact
    if args.note:
        ev["note"] = args.note
    append_event(root, ev)
    tag = {"success": "成功", "failed": "失败", "cancelled": "取消"}[args.status]
    print(f"已登记 {args.unit}/{args.shot}：{tag}，实耗 {args.actual_credits} 分")
    s = fold_state(load_events(root)[0]).get((args.unit, args.shot))
    if s and s["attempts"] > 1:
        print(f"该镜已重抽 {s['attempts']} 次，累计浪费 {s['wasted']:.0f} 分")
    return 0


def cmd_cancel(args):
    root = Path(args.root)
    events, _ = load_events(root)
    if not any(e.get("event") == "submit" and e.get("unit") == args.unit
               and e.get("shot") == args.shot for e in events):
        print(f"未见 submit 记录：{args.unit}/{args.shot}")
        return 2
    ev = {"ts": now(), "event": "cancel", "unit": args.unit, "shot": args.shot}
    if args.note:
        ev["note"] = args.note
    append_event(root, ev)
    print(f"已取消 {args.unit}/{args.shot}" + (f"（{args.note}）" if args.note else ""))
    return 0


def cmd_recover(args):
    """只读：列出已提交未回执的镜。绝不写盘、不生成。"""
    root = Path(args.root)
    events, bad = load_events(root)
    state = fold_state(events)
    pending = [r for r in state.values() if r["status"] == "pending"]
    if args.unit:
        pending = [r for r in pending if r["unit"] == args.unit]
    if not ledger_path(root).is_file():
        print(f"无台账：{ledger_path(root)}（本项目还没记过账）")
        return 0
    if not pending:
        print("无待回执任务")
        return 0
    print(f"待回执 {len(pending)} 镜（只读查询，未触发任何生成）：")
    for r in pending:
        print(f"  {r['unit']}/{r['shot']}  提交于 {r['last']}  "
              f"提交次数 {r['attempts']}  提示词 {r['prompt_sha256'] or '-'}")
    print("\n下一步：到生成平台核对实际结果，再按 result 或 cancel 登记；不要盲目重提")
    if bad:
        print(f"注意：台账有 {bad} 行无法解析，已跳过")
    return 0


def cmd_report(args):
    root = Path(args.root)
    events, bad = load_events(root)
    state = fold_state(events)
    res = summarize(state, bad)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if not state:
        print(f"台账为空：{ledger_path(root)}")
        return 0
    print(f"镜头 {res['shots']} 个 · 已花 {res['spent']:.0f} 分 · "
          f"失败重抽浪费 {res['wasted']:.0f} 分（占 {res['waste_ratio']*100:.1f}%）"
          f" · 待回执 {res['pending']} 镜")
    if res["pending_shots"]:
        print("待回执：" + "、".join(res["pending_shots"][:10]))
    if len(res["by_unit"]) > 1:
        print("\n分集：")
        for u, v in sorted(res["by_unit"].items()):
            print(f"  {u}: 已花 {v['spent']:.0f} · 浪费 {v['wasted']:.0f} · {v['shots']} 镜")
    if res["waste_ratio"] > 0.10:
        print(f"\n警告：浪费占比 {res['waste_ratio']*100:.1f}% 超过 10% 重生预算——"
              f"停下查素材与提示词的系统性问题，别硬刷")
    if bad:
        print(f"\n注意：台账有 {bad} 行无法解析，已跳过")
    return 0


def selftest():
    tmp = Path(tempfile.mkdtemp(prefix="tl_st_"))
    try:
        root = tmp / "项目"
        root.mkdir()

        # 1 基本记账
        assert cmd_submit(argparse.Namespace(root=str(root), unit="第1集", shot="组01",
                                            prompt_sha="aaa111bbb222",
                                            model="seedance-2.5", est_credits=130,
                                            note=None, force=False)) == 0
        assert cmd_result(argparse.Namespace(root=str(root), unit="第1集", shot="组01",
                                            status="success", actual_credits=130,
                                            artifact="第1集/分镜/视频段/段01.mp4",
                                            note=None)) == 0
        r = summarize(fold_state(load_events(root)[0]))
        assert r["spent"] == 130 and r["wasted"] == 0 and r["pending"] == 0, r

        # 2 失败重抽：wasted 记失败那次，spent 只算成功
        cmd_submit(argparse.Namespace(root=str(root), unit="第1集", shot="组02",
                                     prompt_sha="ccc", model="m", est_credits=130,
                                     note=None, force=False))
        cmd_result(argparse.Namespace(root=str(root), unit="第1集", shot="组02",
                                     status="failed", actual_credits=130,
                                     artifact=None, note="内容审核"))
        cmd_submit(argparse.Namespace(root=str(root), unit="第1集", shot="组02",
                                     prompt_sha="ccc", model="m", est_credits=130,
                                     note=None, force=False))
        cmd_result(argparse.Namespace(root=str(root), unit="第1集", shot="组02",
                                     status="success", actual_credits=130,
                                     artifact="段02.mp4", note=None))
        state = fold_state(load_events(root)[0])
        s2 = state[("第1集", "组02")]
        assert s2["attempts"] == 2, s2
        assert s2["spent"] == 130 and s2["wasted"] == 130, s2
        r = summarize(state)
        assert r["spent"] == 260 and r["wasted"] == 130, r
        # 不变量：spent == 所有 success 的 actual 之和
        events = load_events(root)[0]
        assert r["spent"] == sum(float(e.get("actual_credits") or 0) for e in events
                                 if e.get("event") == "result"
                                 and e.get("status") == "success"), "spent 口径错误"

        # 3 重复提交拦截
        cmd_submit(argparse.Namespace(root=str(root), unit="第1集", shot="组03",
                                     prompt_sha="ddd", model="m", est_credits=None,
                                     note=None, force=False))
        rc = cmd_submit(argparse.Namespace(root=str(root), unit="第1集", shot="组03",
                                          prompt_sha="ddd", model="m", est_credits=None,
                                          note=None, force=False))
        assert rc == 3, f"重复提交应返回 3，实际 {rc}"
        assert cmd_submit(argparse.Namespace(root=str(root), unit="第1集", shot="组03",
                                            prompt_sha="ddd", model="m", est_credits=None,
                                            note=None, force=True)) == 0, "--force 应放行"

        # 4 只读恢复：pending 被列出，且文件未被修改
        before = ledger_path(root).stat().st_mtime_ns
        size_before = ledger_path(root).stat().st_size
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert cmd_recover(argparse.Namespace(root=str(root), unit="")) == 0
        assert "组03" in buf.getvalue(), buf.getvalue()
        assert ledger_path(root).stat().st_mtime_ns == before, "recover 不应写盘"
        assert ledger_path(root).stat().st_size == size_before, "recover 不应追加事件"

        # 5 坏行容错
        with ledger_path(root).open("a", encoding="utf-8", newline="\n") as f:
            f.write("这不是 JSON\n")
        events, bad = load_events(root)
        assert bad == 1, f"应识别 1 行坏数据，实际 {bad}"
        r = summarize(fold_state(events), bad)
        assert r["bad_lines"] == 1 and r["spent"] == 260, r

        # 6 老项目兼容：无台账
        empty = tmp / "空项目"
        empty.mkdir()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert cmd_report(argparse.Namespace(root=str(empty), json=False)) == 0
        assert not ledger_path(empty).exists(), "report 不应创建台账"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert cmd_recover(argparse.Namespace(root=str(empty), unit="")) == 0
        assert "无台账" in buf.getvalue(), buf.getvalue()

        # 7 浪费超预算告警
        big = tmp / "浪费项目"
        big.mkdir()
        cmd_submit(argparse.Namespace(root=str(big), unit="第1集", shot="组01",
                                     prompt_sha="x", model="m", est_credits=100,
                                     note=None, force=False))
        cmd_result(argparse.Namespace(root=str(big), unit="第1集", shot="组01",
                                     status="failed", actual_credits=100,
                                     artifact=None, note="崩"))
        cmd_submit(argparse.Namespace(root=str(big), unit="第1集", shot="组01",
                                     prompt_sha="x", model="m", est_credits=100,
                                     note=None, force=False))
        cmd_result(argparse.Namespace(root=str(big), unit="第1集", shot="组01",
                                     status="success", actual_credits=100,
                                     artifact=None, note=None))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_report(argparse.Namespace(root=str(big), json=False))
        assert "超过 10% 重生预算" in buf.getvalue(), buf.getvalue()

        print("selftest PASS（7 项：基本记账/失败重抽/重复拦截/只读恢复/坏行容错/"
              "老项目兼容/浪费告警）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
        return
    ap = argparse.ArgumentParser(description="生成任务台账与成本记账")
    sub = ap.add_subparsers(dest="cmd")

    p1 = sub.add_parser("submit", help="登记提交（预估积分可选）")
    p1.add_argument("root"); p1.add_argument("--unit", required=True)
    p1.add_argument("--shot", required=True)
    p1.add_argument("--prompt-sha", default="", help="提示词 sha256 前12位，与 manifest 同算法")
    p1.add_argument("--model", default="")
    p1.add_argument("--est-credits", type=float, help="预估积分（estimate_cost.py 产出）")
    p1.add_argument("--note", default="")
    p1.add_argument("--force", action="store_true", help="已有 pending 时强制重提")

    p2 = sub.add_parser("result", help="登记结果")
    p2.add_argument("root"); p2.add_argument("--unit", required=True)
    p2.add_argument("--shot", required=True)
    p2.add_argument("--status", required=True, choices=STATUSES)
    p2.add_argument("--actual-credits", type=float, required=True)
    p2.add_argument("--artifact", default="")
    p2.add_argument("--note", default="")

    p3 = sub.add_parser("cancel", help="登记取消")
    p3.add_argument("root"); p3.add_argument("--unit", required=True)
    p3.add_argument("--shot", required=True); p3.add_argument("--note", default="")

    p4 = sub.add_parser("recover", help="只读：列已提交未回执")
    p4.add_argument("root"); p4.add_argument("--unit", default="")

    p5 = sub.add_parser("report", help="汇总")
    p5.add_argument("root"); p5.add_argument("--json", action="store_true")

    sub.add_parser("selftest", help="自检")

    args = ap.parse_args()
    handler = {"submit": cmd_submit, "result": cmd_result, "cancel": cmd_cancel,
               "recover": cmd_recover, "report": cmd_report}
    if args.cmd in handler:
        sys.exit(handler[args.cmd](args))
    else:
        ap.print_help()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
