#!/usr/bin/env python3
"""skill-orchestrator runtime.

Local skill-library discovery, indexing and diffing.

Read-only against the skill library; writes only to this skill's own state/.
Python 3 stdlib only. Every command prints a short single status line so the
model's per-call cost stays flat.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
DISCOVERY = STATE / "discovery.json"
INDEX = STATE / "skill-index.json"

DESC_LIMIT = 240        # chars kept per skill description in the index
LIST_DESC_LIMIT = 120   # chars shown in the compact listing
HISTORY_CAP = 100       # max removed-history entries kept

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path: Path, data) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def root_stat(root: Path) -> tuple[int, int]:
    """Anchor probe: (subdirectory count, root mtime). Only structural changes
    (skill folder added/removed) alter these; content edits do not."""
    try:
        entries = len([p for p in root.iterdir() if p.is_dir()])
    except OSError:
        entries = 0
    try:
        mtime = int(root.stat().st_mtime)
    except OSError:
        mtime = 0
    return entries, mtime


def parse_skill_dir(skill_dir: Path) -> tuple[str, str, int]:
    """Parse (name, description, mtime) from a skill's SKILL.md frontmatter."""
    smd = skill_dir / "SKILL.md"
    try:
        mtime = int(smd.stat().st_mtime)
    except OSError:
        mtime = 0
    name, description = skill_dir.name, ""
    try:
        text = smd.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return name, "(unreadable)", mtime
    fm = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if fm:
        body = fm.group(1)
        lines = body.splitlines()
        i = 0
        top_key_re = re.compile(r"^([A-Za-z0-9_.-]+):\s*(.*)$")
        while i < len(lines):
            m = top_key_re.match(lines[i])
            if m:
                key = m.group(1)
                val = m.group(2).strip().strip("\"'")
                i += 1
                if key == "description" and (
                        not val or val.rstrip("+-").strip() in ("|", ">")):
                    # YAML block scalar: gather following indented lines
                    parts = []
                    while i < len(lines):
                        s = lines[i]
                        if s.startswith((" ", "\t")) or not s.strip():
                            if s.strip():
                                parts.append(s.strip())
                            i += 1
                        else:
                            break
                    val = " ".join(parts)
                if key == "name" and val:
                    name = val
                elif key == "description" and val:
                    description = val
            else:
                i += 1
    if not description:
        description = "(no description)"
    return name, description[:DESC_LIMIT], mtime


def discover_from_anchor() -> Path | None:
    """Locate the skills root by anchoring on this skill's own folder:
    walk upward; a candidate root is either a directory named 'skills' holding
    skill folders, or an ancestor containing a 'skills' directory that does."""

    def looks_like_root(candidate: Path) -> bool:
        if not candidate.is_dir():
            return False
        try:
            subs = [p for p in candidate.iterdir() if p.is_dir()]
        except OSError:
            return False
        return any((p / "SKILL.md").is_file() for p in subs)

    cur = ROOT.parent
    while cur is not None and cur != cur.parent:
        if cur.name == "skills" and looks_like_root(cur):
            return cur
        sib = cur / "skills"
        if looks_like_root(sib):
            return sib
        cur = cur.parent
    return None


def get_root(cli_root: str | None = None) -> Path | None:
    """Resolve the skills root: explicit flag > cached discovery > anchor."""
    if cli_root:
        p = Path(cli_root).expanduser()
        if p.is_dir():
            p = p.resolve()
            save_json(DISCOVERY, {"root": str(p), "source": "user",
                                  "discoveredAt": now()})
            return p
        return None
    cached = load_json(DISCOVERY, {})
    root_s = cached.get("root")
    if root_s and Path(root_s).is_dir():
        return Path(root_s)
    found = discover_from_anchor()
    if found is not None:
        save_json(DISCOVERY, {"root": str(found), "source": "anchor",
                              "discoveredAt": now()})
    return found


def index_default() -> dict:
    return {
        "meta": {"root": "", "total": 0, "lastSync": None,
                 "anchor": {"entries": 0, "mtime": 0},
                 "stats": {"added": 0, "removed": 0, "updated": 0}},
        "skills": [],
        "history": {"removed": []},
    }


def build(root: Path) -> dict:
    idx = index_default()
    entries, mtime = root_stat(root)
    added = 0
    for d in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
        name, description, sm = parse_skill_dir(d)
        idx["skills"].append({"name": name, "desc": description,
                              "mtime": sm, "path": str(d)})
        added += 1
    idx["meta"].update({
        "root": str(root), "total": len(idx["skills"]), "lastSync": now(),
        "anchor": {"entries": entries, "mtime": mtime},
        "stats": {"added": added, "removed": 0, "updated": 0},
    })
    save_json(INDEX, idx)
    return idx


def sync(root: Path, deep: bool) -> dict:
    idx = load_json(INDEX, index_default())
    old = {s["name"]: s for s in idx["skills"]}
    entries, mtime = root_stat(root)

    seen: dict[str, int] = {}
    for d in root.iterdir():
        smd = d / "SKILL.md"
        if smd.is_file():
            try:
                seen[d.name] = int(smd.stat().st_mtime)
            except OSError:
                seen[d.name] = 0

    added = updated = 0
    new_skills = []
    for dname in sorted(seen):
        if dname in old:
            rec = old[dname]
            if deep and rec.get("mtime") != seen[dname]:
                name, description, sm = parse_skill_dir(root / dname)
                rec.update(name=name, desc=description, mtime=sm,
                           path=str(root / dname))
                updated += 1
        else:
            name, description, sm = parse_skill_dir(root / dname)
            new_skills.append({"name": name, "desc": description, "mtime": sm,
                               "path": str(root / dname)})
            added += 1

    gone = [n for n in old if n not in seen]
    removed = len(gone)
    if removed:
        idx["history"]["removed"] = (
            [{"name": n, "removedAt": now()} for n in gone]
            + idx["history"].get("removed", [])
        )[:HISTORY_CAP]

    idx["skills"] = [s for s in idx["skills"] if s["name"] not in gone]
    idx["skills"].extend(new_skills)
    idx["skills"].sort(key=lambda s: s["name"])
    idx["meta"].update({
        "root": str(root), "total": len(idx["skills"]), "lastSync": now(),
        "anchor": {"entries": entries, "mtime": mtime},
        "stats": {"added": added, "removed": removed, "updated": updated},
    })
    save_json(INDEX, idx)
    return idx


def print_skills(idx: dict) -> None:
    for s in idx["skills"]:
        d = s["desc"].replace("\n", " ")
        print(f"{s['name']}\t{d[:LIST_DESC_LIMIT]}\t{s['path']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", nargs="?", default="probe",
                    choices=["probe", "build", "sync", "refresh",
                             "list", "discover"])
    ap.add_argument("--root", default=None,
                    help="explicit skills-root path")
    args = ap.parse_args()

    if args.command == "discover":
        if not args.root:
            print("NEED_INPUT missing --root")
            return
        r = get_root(args.root)
        print(f"ROOT_OK {r}" if r else "NEED_INPUT invalid path")
        return

    root = get_root()
    if root is None:
        print("NEED_INPUT skills root not found; provide it once via: "
              "discover --root <path>")
        return
    root = Path(root)

    if args.command == "build":
        idx = build(root)
        print(f"First index built: {idx['meta']['total']} skills recorded.")
        return

    if args.command == "list":
        print_skills(load_json(INDEX, index_default()))
        return

    if args.command in ("sync", "refresh"):
        idx = sync(root, deep=(args.command == "refresh"))
        st = idx["meta"]["stats"]
        if st["added"] == st["removed"] == st["updated"] == 0:
            print("SYNC_NO_DIFF")
        else:
            print(f"Sync: added {st['added']} · removed {st['removed']} · "
                  f"updated {st['updated']} · total {idx['meta']['total']}")
        return

    # probe (default): anchor-based staleness check
    idx = load_json(INDEX, None)
    if idx is None:
        print(f"FIRST_RUN {root}")
        return
    entries, mtime = root_stat(root)
    anchor = idx["meta"].get("anchor") or {"entries": 0, "mtime": 0}
    if (entries, mtime) == (anchor["entries"], anchor["mtime"]):
        print("NO_CHANGE")
    else:
        print("CHANGED")


if __name__ == "__main__":
    main()
