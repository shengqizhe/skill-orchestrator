#!/usr/bin/env python3
"""skill-orchestrator runtime.

Local skill-library discovery, indexing and diffing.

Read-only against the skill library; writes only to this skill's own state/.
Python 3 stdlib only (hand-written YAML frontmatter subset parser, no pyyaml).
Every command prints ONE short status line on stdout so the model's per-call
cost stays flat; diagnostics go to stderr and are only shown with --verbose.
'protocol' prints the authoritative status vocabulary — SKILL.md mirrors it.
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

SELF = ROOT             # this skill's own folder; never index it

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def vlog(verbose: bool, msg: str) -> None:
    """Diagnostics only ever go to stderr, keeping stdout a single line."""
    if verbose:
        print(msg, file=sys.stderr)


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


def is_self(d: Path) -> bool:
    """True when d is this skill's own folder (it lives inside the scanned
    library). Self-exclusion keeps a running install from indexing itself."""
    try:
        return d.resolve() == SELF
    except OSError:
        return False


# --------------------------------------------------------------------------
# SKILL.md frontmatter subset parser
#
# Contract (documented in SKILL.md's 已知副作用/局限):
#   * frontmatter must open the file:  ---<LF> ... <LF>---
#   * top-level keys sit at column 0; `name`/`description` are read,
#     other keys (license, metadata, version, ...) are skipped.
#   * `description` supports: inline plain/quoted; plain continuation onto
#     following indented lines; YAML block scalars `|`/`>` with any chomp
#     (`|`, `|-`, `|+`, `>`, `>-`, `>+`).
#   * block/literal/folded styles are all normalised to a single whitespace
#     run -> one space, because the index only feeds trigger matching.
#   * last occurrence wins; missing name -> folder name; no/empty
#     description -> "(no description)".
# Out of scope (rejected deliberately): quoted escapes, nested maps,
# list values, flow scalars, comments inside block scalars.
# --------------------------------------------------------------------------
KEY_RE = re.compile(r"^([A-Za-z0-9_.-]+):(.*)$")


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_skill_dir(skill_dir: Path) -> tuple[str, str, int]:
    """Parse (name, description, mtime) from a skill's SKILL.md frontmatter."""
    smd = skill_dir / "SKILL.md"
    try:
        mtime = int(smd.stat().st_mtime)
    except OSError:
        mtime = 0
    name = skill_dir.name
    description = ""
    try:
        text = smd.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return name, "(unreadable)", mtime
    fm = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not fm:
        return name, "(no description)", mtime

    lines = fm.group(1).splitlines()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or line.startswith((" ", "\t")):
            i += 1
            continue
        m = KEY_RE.match(line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "name":
            if val:
                name = _unquote(val)
            i += 1
            continue
        if key != "description":
            i += 1
            continue

        # -- description ---------------------------------------------------
        if val[:1] in ("|", ">"):
            # block scalar (chomp marker ignored; whitespace is normalised)
            parts: list[str] = []
            i += 1
            while i < n and (not lines[i].strip()
                             or lines[i].startswith((" ", "\t"))):
                t = lines[i].strip()
                if t:
                    parts.append(t)
                i += 1
            description = normalize_space(" ".join(parts))
        else:
            # inline plain/quoted scalar, plus YAML plain-style continuation
            # on following indented lines
            parts = [_unquote(val)] if val else []
            i += 1
            while i < n and lines[i].startswith((" ", "\t")):
                t = lines[i].strip()
                if t and not t.startswith("#"):
                    parts.append(t)
                i += 1
            description = normalize_space(" ".join(parts))
    if not description:
        description = "(no description)"
    return name, description[:DESC_LIMIT], mtime


# --------------------------------------------------------------------------
# discovery / state
# --------------------------------------------------------------------------
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


def get_root(cli_root: str | None = None, verb: bool = False) -> Path | None:
    """Resolve the skills root: explicit flag > cached discovery > anchor."""
    if cli_root:
        p = Path(cli_root).expanduser()
        if p.is_dir():
            p = p.resolve()
            vlog(verb, f"explicit root {p} (not persisted)")
            return p
        return None
    cached = load_json(DISCOVERY, {})
    root_s = cached.get("root")
    if root_s and Path(root_s).is_dir():
        vlog(verb, f"cached root {root_s} (discovery.json)")
        return Path(root_s)
    if root_s:
        vlog(verb, f"cached root {root_s} missing; re-anchoring")
    found = discover_from_anchor()
    if found is not None:
        save_json(DISCOVERY, {"root": str(found), "source": "anchor",
                              "discoveredAt": now()})
        vlog(verb, f"anchored skills root {found}")
    else:
        vlog(verb, "anchor walk found no skills root")
    return found


def index_default() -> dict:
    return {
        "meta": {"root": "", "total": 0, "lastSync": None,
                 "anchor": {"entries": 0, "mtime": 0},
                 "stats": {"added": 0, "removed": 0, "updated": 0}},
        "skills": [],
        "history": {"removed": []},
    }


def candidate_skills(root: Path) -> list[Path]:
    """Skill folders under root: have a SKILL.md and are not this skill."""
    return [d for d in root.iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file() and not is_self(d)]


def _dirname(rec: dict) -> str:
    """Directory identity of an index record.

    The folder name -- not the frontmatter name -- is the physical identity
    sync/refresh operate on (probe's anchor check is directory-grained too).
    A folder's frontmatter name may differ from its folder name (marketplace
    slug dirs), and two folders may share one frontmatter name; indexing by
    folder keeps sync convergent in both cases.
    """
    return Path(rec.get("path", "")).name or rec.get("name", "")


def build(root: Path, dry: bool, verb: bool) -> dict:
    idx = index_default()
    entries, mtime = root_stat(root)
    dirs = candidate_skills(root)
    vlog(verb, f"scanning {root} ({len(dirs)} skill dirs)")
    for d in sorted(dirs):
        name, description, sm = parse_skill_dir(d)
        vlog(verb, f"  + {name}  ({d.name})")
        idx["skills"].append({"name": name, "desc": description,
                              "mtime": sm, "path": str(d)})
    idx["meta"].update({
        "root": str(root), "total": len(idx["skills"]), "lastSync": now(),
        "anchor": {"entries": entries, "mtime": mtime},
        "stats": {"added": len(idx["skills"]), "removed": 0, "updated": 0},
    })
    if not dry:
        save_json(INDEX, idx)
    return idx


def sync(root: Path, deep: bool, dry: bool, verb: bool) -> dict:
    idx = load_json(INDEX, index_default())
    old = {_dirname(s): s for s in idx["skills"]}
    entries, mtime = root_stat(root)

    seen: dict[str, int] = {}
    for d in candidate_skills(root):
        smd = d / "SKILL.md"
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
                vlog(verb, f"  ~ {dname}")
        else:
            name, description, sm = parse_skill_dir(root / dname)
            new_skills.append({"name": name, "desc": description, "mtime": sm,
                               "path": str(root / dname)})
            added += 1
            vlog(verb, f"  + {name}  ({dname})")

    gone = [d for d in old if d not in seen]
    removed = len(gone)
    for g in gone:
        vlog(verb, f"  - {old[g].get('name', g)}  ({g})")
    if removed:
        idx["history"]["removed"] = (
            [{"dirname": g, "name": old[g].get("name", ""),
              "removedAt": now()} for g in gone]
            + idx["history"].get("removed", [])
        )[:HISTORY_CAP]

    idx["skills"] = [s for s in idx["skills"] if _dirname(s) not in gone]
    idx["skills"].extend(new_skills)
    idx["skills"].sort(key=lambda s: s["name"])
    idx["meta"].update({
        "root": str(root), "total": len(idx["skills"]), "lastSync": now(),
        "anchor": {"entries": entries, "mtime": mtime},
        "stats": {"added": added, "removed": removed, "updated": updated},
    })
    if not dry:
        save_json(INDEX, idx)
    return idx


def print_skills(idx: dict) -> None:
    for s in idx["skills"]:
        d = s["desc"].replace("\n", " ")
        print(f"{s['name']}\t{d[:LIST_DESC_LIMIT]}\t{s['path']}")


# --------------------------------------------------------------------------
# dev commands
# --------------------------------------------------------------------------
def run_reset(dry: bool, verb: bool) -> None:
    targets = [p for p in (DISCOVERY, INDEX) if p.exists()]
    if STATE.is_dir():
        targets += sorted(STATE.glob("*.tmp"))
    for t in targets:
        vlog(verb, f"remove {t.relative_to(ROOT)}")
    if not dry:
        for t in targets:
            try:
                t.unlink()
            except OSError as e:
                print(f"STATE_RESET partial failure: {e}", file=sys.stderr)
        try:
            STATE.rmdir()
        except OSError:
            pass
    print("DRY_RUN STATE_RESET" if dry else "STATE_RESET")


PROTOCOL_LINES = """protocol v3
# probe (default) status lines
NO_CHANGE
CHANGED
FIRST_RUN <root>
NEED_INPUT <reason>
ROOT_OK <root>
# build / sync report lines
First index built: N skills recorded.
Sync: added X \u00b7 removed Y \u00b7 updated Z \u00b7 total T
SYNC_NO_DIFF
# reset report line
STATE_RESET
# list rows: one per indexed skill; no index yet prints:
NEED_INDEX
# empty output from list = empty library (run probe first to confirm state)
<name>\t<desc (<=120 chars)>\t<path>
# modifiers: --dry-run prefixes 'DRY_RUN ' to the report line; --verbose
# adds diagnostics on stderr only (stdout stays single-line)""".replace(
    "\\t", "\t")


def print_protocol() -> None:
    for ln in PROTOCOL_LINES.splitlines():
        print(ln)


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", nargs="?", default="probe",
                    choices=["probe", "build", "sync", "refresh",
                             "list", "discover", "reset", "protocol"])
    ap.add_argument("--root", default=None,
                    help="explicit skills-root path (dev tool; not persisted "
                         "except by 'discover')")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="extra diagnostics to stderr; stdout stays one line")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen without writing anything")
    args = ap.parse_args()
    verb = args.verbose

    if args.command == "protocol":
        print_protocol()
        return

    if args.command == "reset":
        run_reset(args.dry_run, verb)
        return

    if args.command == "discover":
        if not args.root:
            print("NEED_INPUT discover requires --root <path>")
            return
        p = Path(args.root).expanduser()
        if not p.is_dir():
            print("NEED_INPUT invalid root path")
            return
        root = p.resolve()
        if args.dry_run:
            print(f"DRY_RUN ROOT_OK {root}")
        else:
            save_json(DISCOVERY, {"root": str(root), "source": "user",
                                  "discoveredAt": now()})
            vlog(verb, f"discovery cached at {DISCOVERY}")
            print(f"ROOT_OK {root}")
        return

    if args.root:
        p = Path(args.root).expanduser()
        if not p.is_dir():
            print("NEED_INPUT invalid --root path")
            return
        root = p.resolve()
        vlog(verb, f"explicit root {root} (not persisted)")
    else:
        root = get_root(verb=verb)
        if root is None:
            print("NEED_INPUT skills root not found; provide it once via: "
                  "discover --root <path>")
            return
        root = Path(root)
        vlog(verb, f"root resolved: {root}")

    pfx = "DRY_RUN " if args.dry_run else ""

    if args.command == "build":
        idx = build(root, args.dry_run, verb)
        print(f"{pfx}First index built: {idx['meta']['total']} "
              "skills recorded.")
        return

    if args.command == "list":
        idx = load_json(INDEX, None)
        if idx is None:
            print("NEED_INDEX")
            return
        print_skills(idx)
        return

    if args.command in ("sync", "refresh"):
        idx = sync(root, deep=(args.command == "refresh"),
                   dry=args.dry_run, verb=verb)
        st = idx["meta"]["stats"]
        if st["added"] == st["removed"] == st["updated"] == 0:
            print(f"{pfx}SYNC_NO_DIFF")
        else:
            print(f"{pfx}Sync: added {st['added']} \u00b7 "
                  f"removed {st['removed']} \u00b7 "
                  f"updated {st['updated']} \u00b7 "
                  f"total {idx['meta']['total']}")
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
