"""Display a published story episode in the terminal.

Usage:
    python -m scripts.show_story --world_id eldoria-1
    python -m scripts.show_story --world_id eldoria-1 --episode E001
    python -m scripts.show_story --world_id eldoria-1 --all
    python -m scripts.show_story --list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUBLISH_ROOT = Path("publish/out/story")

# ANSI color codes
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
RED = "\033[31m"
RESET = "\033[0m"
RULE = f"{DIM}{'-' * 60}{RESET}"


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    return json.loads(path.read_bytes())


def _list_worlds() -> list[Path]:
    if not PUBLISH_ROOT.exists():
        return []
    return sorted(d for d in PUBLISH_ROOT.iterdir() if d.is_dir())


def _list_episodes(world_dir: Path) -> list[Path]:
    if not world_dir.exists():
        return []
    return sorted(d for d in world_dir.iterdir() if d.is_dir())


def _latest_episode(world_dir: Path) -> Path | None:
    episodes = _list_episodes(world_dir)
    return episodes[-1] if episodes else None


def show_list():
    """List all worlds and their episodes."""
    worlds = _list_worlds()
    if not worlds:
        print(f"{DIM}No published stories found in {PUBLISH_ROOT}{RESET}")
        return

    print(f"\n{BOLD}{CYAN}Published Stories{RESET}\n{RULE}")
    for world_dir in worlds:
        episodes = _list_episodes(world_dir)
        world_state = _load_json(episodes[-1] / "world_state.json") if episodes else None
        name = world_state.get("name", world_dir.name) if world_state else world_dir.name
        genre = world_state.get("genre", "") if world_state else ""
        label = f"{name} ({genre})" if genre else name
        print(f"\n  {BOLD}{label}{RESET}  {DIM}[{world_dir.name}]{RESET}")
        for ep_dir in episodes:
            manifest = _load_json(ep_dir / "manifest.json") or {}
            episode = _load_json(ep_dir / "episode.json") or {}
            title = episode.get("episode_title", ep_dir.name)
            version = manifest.get("version", ep_dir.name)
            words = episode.get("word_count", "?")
            print(f"    {GREEN}{version}{RESET}  {title}  {DIM}({words} words){RESET}")
    print()


def show_episode(ep_dir: Path, *, compact: bool = False):
    """Display a single episode."""
    manifest = _load_json(ep_dir / "manifest.json") or {}
    episode = _load_json(ep_dir / "episode.json") or {}
    world_state = _load_json(ep_dir / "world_state.json") or {}
    new_claims = _load_json(ep_dir / "new_claims.json") or []
    narration = (ep_dir / "narration_script.txt").read_text() if (ep_dir / "narration_script.txt").exists() else None
    recap_file = ep_dir / "recap.md"
    recap = recap_file.read_text().strip() if recap_file.exists() else None

    version = manifest.get("version", ep_dir.name)
    world_id = manifest.get("scope_id", "?")
    world_name = world_state.get("name", world_id)
    genre = world_state.get("genre", "")
    tone = world_state.get("tone", "")
    title = episode.get("episode_title", "Untitled")
    ep_num = episode.get("episode_number", "?")
    premise = episode.get("premise", "")
    compliance = episode.get("compliance_status", "?")
    word_count = episode.get("word_count", "?")

    # Header
    print(f"\n{RULE}")
    print(f"{BOLD}{CYAN}  {world_name}{RESET}  {DIM}{genre} · {tone}{RESET}")
    print(f"{BOLD}  Episode {ep_num}: {title}{RESET}  {DIM}[{version}]{RESET}")
    print(RULE)

    # Premise
    if premise:
        print(f"\n{YELLOW}Premise:{RESET} {premise}")

    # Recap
    if recap:
        # Strip markdown header if present
        lines = recap.strip().splitlines()
        text = "\n".join(l for l in lines if not l.startswith("#")).strip()
        if text:
            print(f"\n{DIM}-- Previously --{RESET}")
            print(f"{DIM}{text}{RESET}")

    # Scenes
    scenes = episode.get("scenes", [])
    acts = episode.get("act_structure", [])
    act_map = {a.get("act"): a for a in acts}

    print(f"\n{DIM}-- Story --{RESET}\n")

    # Map scenes to acts via scene_plans if available
    scene_plans = episode.get("scene_plans") or []
    scene_act = {}
    for sp in scene_plans:
        scene_act[sp.get("scene_id")] = sp.get("act")

    current_act = None
    for scene in scenes:
        sid = scene.get("scene_id", "")
        act_num = scene_act.get(sid)
        if act_num and act_num != current_act:
            current_act = act_num
            act_info = act_map.get(act_num, {})
            act_title = act_info.get("title", f"Act {act_num}")
            print(f"  {BOLD}{MAGENTA}Act {act_num}: {act_title}{RESET}\n")

        text = scene.get("text", "")
        for para in text.split("\n"):
            if para.strip():
                print(f"  {para.strip()}")
        print()

    print(f"  {DIM}-- {word_count} words --{RESET}")

    # Narration script
    if narration and not compact:
        print(f"\n{DIM}-- Narration Script --{RESET}\n")
        for line in narration.strip().splitlines():
            if line.startswith("[NARRATOR]"):
                print(f"  {CYAN}{line}{RESET}")
            elif line.startswith("[VOICE:"):
                print(f"  {YELLOW}{line}{RESET}")
            else:
                print(f"  {line}")
        print()

    # Characters
    characters = world_state.get("characters", [])
    if characters and not compact:
        print(f"{DIM}-- Characters --{RESET}\n")
        for c in characters:
            name = c.get("name", "?")
            role = c.get("role", "")
            arc = c.get("arc_stage", "")
            traits = ", ".join(c.get("traits", []))
            alive = "" if c.get("alive", True) else f" {RED}[deceased]{RESET}"
            print(f"  {BOLD}{name}{RESET} {DIM}({role}, {arc}){RESET}{alive}")
            if traits:
                print(f"    traits: {traits}")
        print()

    # Active threads
    threads = world_state.get("active_threads", [])
    if threads and not compact:
        print(f"{DIM}-- Active Threads --{RESET}\n")
        for t in threads:
            title = t.get("title", "?")
            tag = t.get("thematic_tag", "")
            status = t.get("status", "")
            color = GREEN if status == "open" else DIM
            print(f"  {color}* {title}{RESET}  {DIM}[{tag}]{RESET}")
        print()

    # Canon updates
    if new_claims and not compact:
        print(f"{DIM}-- Canon Updates --{RESET}\n")
        for c in new_claims:
            ctype = c.get("claim_type", "?")
            stmt = c.get("statement", "?")
            conf = c.get("confidence", 0)
            print(f"  {GREEN}+{RESET} [{ctype}] {stmt}  {DIM}(conf: {conf}){RESET}")
        print()

    # QA status
    print(f"{DIM}-- QA --{RESET}")
    color = GREEN if compliance == "PASS" else RED
    print(f"  Compliance: {color}{compliance}{RESET}")
    print(f"  Published: {DIM}{ep_dir}{RESET}")
    print(RULE)
    print()


def main():
    parser = argparse.ArgumentParser(description="Display published story episodes")
    parser.add_argument("--world_id", "-w", help="World ID to display")
    parser.add_argument("--episode", "-e", help="Episode version (e.g. E001). Default: latest")
    parser.add_argument("--all", "-a", action="store_true", help="Show all episodes for the world")
    parser.add_argument("--list", "-l", action="store_true", help="List all published worlds and episodes")
    parser.add_argument("--compact", "-c", action="store_true", help="Compact view (story text only)")
    parser.add_argument("--publish-root", help="Override publish root directory")
    args = parser.parse_args()

    if args.publish_root:
        global PUBLISH_ROOT
        PUBLISH_ROOT = Path(args.publish_root)

    if args.list:
        show_list()
        return

    if not args.world_id:
        # If only one world exists, use it
        worlds = _list_worlds()
        if len(worlds) == 1:
            args.world_id = worlds[0].name
        else:
            show_list()
            if worlds:
                print(f"Specify a world with {BOLD}--world_id <id>{RESET}\n")
            return

    world_dir = PUBLISH_ROOT / args.world_id
    if not world_dir.exists():
        print(f"{RED}World not found: {args.world_id}{RESET}")
        print(f"Published at: {PUBLISH_ROOT}")
        show_list()
        sys.exit(1)

    if args.all:
        for ep_dir in _list_episodes(world_dir):
            show_episode(ep_dir, compact=args.compact)
        return

    if args.episode:
        ep_dir = world_dir / args.episode
        if not ep_dir.exists():
            print(f"{RED}Episode not found: {args.episode}{RESET}")
            print("Available:")
            for d in _list_episodes(world_dir):
                print(f"  {d.name}")
            sys.exit(1)
    else:
        ep_dir = _latest_episode(world_dir)
        if ep_dir is None:
            print(f"{RED}No episodes found for world {args.world_id}{RESET}")
            sys.exit(1)

    show_episode(ep_dir, compact=args.compact)


if __name__ == "__main__":
    main()
