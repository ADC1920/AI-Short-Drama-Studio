#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 技能根安装：把本工作区（技能开发源）挂进 DeepSeek Harness 的技能发现根。

DSH 官方技能根（`@deepseek-ai/dsh-skill-filesystem`，同名技能按 rank 从小到大取胜）：
  100  <项目根>/.dsh/skills        ← install 默认目标（项目根=最近含 .git 的祖先）
  200  <项目根>/.agents/skills
  300  Config.customSkillDirs
  400  <DSH_HOME>/skills          ← `--root user` 的目标（默认 ~/.dsh/skills）
  500  <AGENTS_HOME>/skills       （默认 ~/.agents/skills；zcode 与本机共用，只读不写）
发现深度只有一层：`<根>/<技能名>/SKILL.md` 或 `<根>/<技能名>.md`。

本脚本只在 DSH 自己的根下创建一个指向本仓库根的目录联接（Windows junction /
POSIX symlink）：源文件零改动，改工作区即时生效；不触碰 zcode 共享的
`~/.agents/skills`，因而不影响 zcode 侧文件。技能名读自 `SKILL.md` front-matter。

用法:
    python scripts/dsh_link.py install   [--root project|user] [--name <技能名>] [--dry-run]
    python scripts/dsh_link.py uninstall [--root project|user] [--name <技能名>] [--dry-run]
    python scripts/dsh_link.py status
    python scripts/dsh_link.py --selftest
退出码: 0=成功, 1=状态异常/复核失败, 2=用法或安全检查失败
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_SKILL_RANK = 100
USER_SKILL_RANK = 400
SHARED_SKILL_RANK = 500   # ~/.agents/skills：zcode 共用，只读不写


def repo_root():
    """本仓库根（脚本位于 <根>/scripts/ 下）。"""
    return Path(__file__).resolve().parent.parent


def find_project_root(start):
    """最近含 .git 的祖先目录；找不到返回 None（与 DSH 项目根发现口径一致）。"""
    cur = Path(start).resolve()
    for p in (cur, *cur.parents):
        try:
            if (p / ".git").exists():
                return p
        except OSError:
            return None
    return None


def home_dir(env_name, default_name):
    """$<env_name> 优先，否则 ~/<default_name>。"""
    env = os.environ.get(env_name, "")
    return Path(env) if env else Path.home() / default_name


def dsh_home():
    return home_dir("DSH_HOME", ".dsh")


def agents_home():
    return home_dir("DSH_AGENTS_HOME", ".agents")


def read_skill_name(repo):
    """读 SKILL.md front-matter 的 name:；缺失时回退为仓库目录名。"""
    skill_md = Path(repo) / "SKILL.md"
    if skill_md.is_file():
        for line in skill_md.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip("'\"")
                if name:
                    return name
    return Path(repo).name


def is_link(p):
    """目录符号链接或 Windows 目录联接（junction）。"""
    p = Path(p)
    try:
        if p.is_symlink():
            return True
    except OSError:
        pass
    try:
        return getattr(os.path, "isjunction", lambda _p: False)(p)
    except OSError:
        return False


def make_dir_link(link, target):
    """创建目录联接；Windows 走 mklink /J（无需管理员），其它平台用 symlink。"""
    if os.name == "nt":
        r = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            raise OSError((r.stdout or "").strip() or f"mklink 退出码 {r.returncode}")
    else:
        os.symlink(target, link, target_is_directory=True)


def target_root(root_opt, repo):
    """安装根：project=<项目根>/.dsh/skills；user=<DSH_HOME>/skills。"""
    if root_opt == "user":
        return dsh_home() / "skills"
    proj = find_project_root(repo)
    if proj is None:
        return None
    return proj / ".dsh" / "skills"


def install(link, target, dry_run=False):
    """在 link 处建一个指向 target（技能根）的目录联接。"""
    link, target = Path(link), Path(target).resolve()
    if not (target / "SKILL.md").is_file():
        print(f"安全检查失败：目标不是技能根（缺 SKILL.md）: {target}")
        return 2
    if is_link(link):
        try:
            same = link.resolve() == target
        except OSError:
            same = False
        if same:
            print(f"已安装（链接已指向本仓库）: {link}")
            return 0
        print(f"链接已存在但指向别处，拒绝覆盖: {link}")
        return 2
    if link.exists():
        print(f"路径已存在且不是目录联接，拒绝覆盖: {link}")
        return 2
    if dry_run:
        print(f"dry-run：将创建目录联接 {link} -> {target}")
        return 0
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        make_dir_link(link, target)
    except OSError as exc:
        print(f"创建联接失败: {exc}")
        return 2
    ok = is_link(link) and (link / "SKILL.md").is_file()
    print(("安装完成" if ok else "复核失败") + f": {link} -> {target}")
    return 0 if ok else 1


def uninstall(link, dry_run=False):
    """只删除目录联接本身；目标目录原样保留。"""
    link = Path(link)
    if not is_link(link):
        if link.exists():
            print(f"安全检查失败：不是目录联接，拒绝删除: {link}")
            return 2
        print(f"未安装（路径不存在）: {link}")
        return 0
    if dry_run:
        print(f"dry-run：将删除目录联接 {link}")
        return 0
    try:
        if os.name == "nt":
            os.rmdir(link)      # 只移除联接（reparse point），不碰目标内容
        else:
            os.unlink(link)
    except OSError as exc:
        print(f"删除联接失败: {exc}")
        return 1
    print(f"已卸载: {link}")
    return 0


def status():
    repo = repo_root()
    name = read_skill_name(repo)
    proj = find_project_root(repo)
    print(f"仓库根: {repo}")
    print(f"技能名: {name}")
    rows = []
    if proj is not None:
        rows.append(("project", proj / ".dsh" / "skills" / name, PROJECT_SKILL_RANK))
    rows.append(("user", dsh_home() / "skills" / name, USER_SKILL_RANK))
    for label, link, rank in rows:
        if is_link(link):
            state = "已安装 -> " + str(link.resolve()) if (link / "SKILL.md").is_file() else "链接失效"
        elif link.exists():
            state = "存在但非目录联接"
        else:
            state = "未安装"
        print(f"[{label}] rank {rank} {link} | {state}")
    shared = agents_home() / "skills" / name
    if shared.exists():
        print(f"[只读] rank {SHARED_SKILL_RANK} 共享根 {shared}（zcode/其它工具共用；本脚本不写入）")
    return 0


def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "proj"
        (project / ".git").mkdir(parents=True)
        repo = project / "repo"
        (repo / "references").mkdir(parents=True)
        (repo / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: demo\n---\n# demo\n", encoding="utf-8")
        (repo / "references" / "a.md").write_text("a", encoding="utf-8")

        assert find_project_root(repo) == project.resolve(), "项目根发现失败"
        assert read_skill_name(repo) == "demo-skill", "技能名解析失败"

        link = project / ".dsh" / "skills" / "demo-skill"
        assert install(link, repo) == 0, "安装失败"
        assert is_link(link), "未创建目录联接"
        assert (link / "SKILL.md").is_file(), "联接下读不到 SKILL.md"
        assert (link / "SKILL.md").resolve() == (repo / "SKILL.md").resolve(), "联接未指向源文件"
        assert install(link, repo) == 0, "重复安装应幂等"

        # 真实目录不可被覆盖 / 按联接删除
        real = project / ".dsh" / "skills" / "real-skill"
        real.mkdir(parents=True)
        (real / "SKILL.md").write_text("x", encoding="utf-8")
        assert install(real, repo) == 2, "真实目录应拒绝覆盖"
        assert uninstall(real) == 2, "真实目录应拒绝删除"

        # dry-run 不产生副作用
        other = project / ".dsh" / "skills" / "demo-2"
        assert install(other, repo, dry_run=True) == 0
        assert not other.exists(), "dry-run 不应创建联接"

        assert uninstall(link) == 0, "卸载失败"
        assert not link.exists(), "卸载后联接仍存在"
        assert (repo / "SKILL.md").is_file(), "卸载不应影响源目录"

        # 用户根推导（不实际写入）
        prev = os.environ.get("DSH_HOME")
        os.environ["DSH_HOME"] = str(root / "dsh-home")
        try:
            assert dsh_home() == root / "dsh-home", "DSH_HOME 解析失败"
            assert target_root("user", repo) == root / "dsh-home" / "skills", "用户根路径错误"
        finally:
            if prev is None:
                os.environ.pop("DSH_HOME", None)
            else:
                os.environ["DSH_HOME"] = prev

    print("selftest PASS（项目根发现 / 技能名解析 / 联接创建与复核 / 幂等 / "
          "真实目录拒覆盖拒删 / dry-run 无副作用 / 卸载不伤源 / DSH_HOME 解析）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="DSH 技能根安装（项目 .dsh/skills 或用户 ~/.dsh/skills）")
    ap.add_argument("action", nargs="?", choices=["install", "uninstall", "status"], default="status")
    ap.add_argument("--root", choices=["project", "user"], default="project",
                    help="安装根：project（默认，<项目根>/.dsh/skills）或 user（<DSH_HOME>/skills）")
    ap.add_argument("--name", help="技能名（默认读 SKILL.md front-matter）")
    ap.add_argument("--dry-run", action="store_true", help="只显示将执行的动作")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.action == "status":
        return status()
    repo = repo_root()
    name = args.name or read_skill_name(repo)
    base = target_root(args.root, repo)
    if base is None:
        print("未找到项目根（最近含 .git 的祖先目录）；请改用 --root user。")
        return 2
    link = base / name
    if args.action == "install":
        return install(link, repo, args.dry_run)
    return uninstall(link, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
