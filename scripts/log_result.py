#!/usr/bin/env python3
"""
log_result.py — Record a debate result into leaderboard.csv and regenerate LEADERBOARD.md.

Usage:
    python scripts/log_result.py debate_logs/<result_file>.json
    python scripts/log_result.py --folder debate_logs

Workflow:
    1. Run a debate.
    2. Run this script on the resulting log file.
    3. Review the appended row in leaderboard.csv.
    4. Commit: git add debate_logs/ leaderboard.csv LEADERBOARD.md && git commit
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
LEADERBOARD_CSV = REPO_ROOT / "leaderboard.csv"
LEADERBOARD_MD = REPO_ROOT / "LEADERBOARD.md"
GITHUB_REPO = "https://github.com/QuangHPV/NLP-2026_DEBATE"
TZ_OFFSET = timedelta(hours=8)  # +0800


def git(*args):
    result = subprocess.run(["git", "-C", str(REPO_ROOT)] + list(args),
                            capture_output=True, text=True)
    return result.stdout.strip()


def commit_for_file_at(filepath, before_dt):
    """Return the most recent commit hash for filepath that was committed before before_dt.

    Caveat: this uses commit timestamps, not local file state at debate time.
    If a collaborator pushed a commit shortly before the debate but it was not yet
    fetched locally, the auto-detected commit will be wrong. In that case, manually
    edit leaderboard.csv and re-run with --regen to regenerate LEADERBOARD.md.
    """
    iso = before_dt.strftime("%Y-%m-%d %H:%M:%S %z")
    h = git("log", f"--before={iso}", "-1", "--format=%H", "--", filepath)
    return h or ""


def parse_debate_timestamp(log_filename):
    """Extract datetime from filename like: ..._2026-05-18_16-25-21.json"""
    m = LOG_FILENAME_RE.search(log_filename)
    if not m:
        raise ValueError(f"Cannot parse timestamp from filename: {log_filename}")
    date_str, time_str = m.group(1), m.group(2).replace("-", ":")
    tz = timezone(TZ_OFFSET)
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)


def is_debate_log_file(path):
    return path.is_file() and LOG_FILENAME_RE.search(path.name) is not None


def collect_log_paths(target_path):
    if target_path.is_dir():
        return sorted(p for p in target_path.glob("*.json") if is_debate_log_file(p))
    if is_debate_log_file(target_path):
        return [target_path]
    raise ValueError(f"{target_path} is not a debate log file or folder of debate logs")


def load_csv():
    if not LEADERBOARD_CSV.exists():
        return []
    with open(LEADERBOARD_CSV, newline="") as f:
        return list(csv.DictReader(f))


FIELDNAMES = [
    "date", "affirmative", "aff_commit", "negative", "neg_commit",
    "material", "material_commit", "log_file", "aff_votes", "neg_votes", "winner",
    "aff_calls", "neg_calls", "aff_max_turn_s", "neg_max_turn_s",
]

LOG_FILENAME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.json$")


def save_csv(rows):
    with open(LEADERBOARD_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r.get("date", ""), r.get("log_file", "")))


def display_path(path):
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def extract_perf(data):
    """Pull call counts and max per-turn time from a debate JSON. Handles old logs without timing."""
    usage = data.get("usage", {})
    aff_u = usage.get("affirmative", {})
    neg_u = usage.get("negative", {})

    aff_times = aff_u.get("time taken", [])
    neg_times = neg_u.get("time taken", [])

    return {
        "aff_calls": aff_u.get("chat_calls", ""),
        "neg_calls": neg_u.get("chat_calls", ""),
        "aff_max_turn_s": f"{max(aff_times):.1f}" if aff_times else "",
        "neg_max_turn_s": f"{max(neg_times):.1f}" if neg_times else "",
    }


def blob_url(filepath, commit):
    if not commit:
        return filepath
    return f"{GITHUB_REPO}/blob/{commit}/{filepath}"


def _perf_cell(calls, max_s):
    """Format a compact per-side performance string: '14c 112s' or '14c' or '—'."""
    if not calls:
        return "—"
    if max_s:
        return f"{calls}c {max_s}s"
    return f"{calls}c"


def render_md(rows):
    lines = [
        "# Debate Leaderboard",
        "",
        "Each agent filename links to the exact commit that was used during that debate.",
        "Each log links to the recorded transcript and judge votes.",
        "Perf columns: `Nc` = total API calls, `Ms` = max per-turn seconds (blank = timing not recorded).",
        "",
        "| Date | Affirmative | Negative | Material | Score | Winner | Perf (A/N) | Log |",
        "|------|-------------|----------|----------|-------|--------|------------|-----|",
    ]
    for r in rows:
        date = r["date"]
        aff_short = r["aff_commit"][:7] if r.get("aff_commit") else "?"
        neg_short = r["neg_commit"][:7] if r.get("neg_commit") else "?"
        mat_short = r["material_commit"][:7] if r.get("material_commit") else "?"

        aff_url = blob_url(f"students/{r['affirmative']}.py", r.get("aff_commit", ""))
        neg_url = blob_url(f"students/{r['negative']}.py", r.get("neg_commit", ""))
        mat_url = blob_url(f"materials/{r['material']}", r.get("material_commit", ""))
        log_url = f"debate_logs/{r['log_file']}"

        aff_cell = f"[{r['affirmative']} `{aff_short}`]({aff_url})"
        neg_cell = f"[{r['negative']} `{neg_short}`]({neg_url})"
        mat_cell = f"[{r['material']} `{mat_short}`]({mat_url})"
        score = f"{r['aff_votes']}-{r['neg_votes']}"
        winner = r["winner"]
        winner_cell = f"**{winner}**" if winner == "affirmative" else winner

        aff_perf = _perf_cell(r.get("aff_calls", ""), r.get("aff_max_turn_s", ""))
        neg_perf = _perf_cell(r.get("neg_calls", ""), r.get("neg_max_turn_s", ""))
        perf_cell = aff_perf + r" \| " + neg_perf

        lines.append(
            f"| {date} | {aff_cell} | {neg_cell} | {mat_cell} | {score} | {winner_cell} | {perf_cell} | [log]({log_url}) |"
        )

    lines.append("")
    lines.append(
        "_Run `python scripts/log_result.py <log_file>` after a debate to append a row and regenerate this file._"
    )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Record debate results into leaderboard.csv and regenerate LEADERBOARD.md")
    parser.add_argument("target", nargs="?", help="A debate result JSON file or a folder containing debate result JSON files")
    parser.add_argument("--folder", dest="folder", help="Explicitly process all debate result JSON files in this folder")
    parser.add_argument("--regen", action="store_true", help="Regenerate LEADERBOARD.md from leaderboard.csv without adding new rows")
    args = parser.parse_args()

    # --regen: skip CSV append and just regenerate LEADERBOARD.md from existing CSV
    if args.regen:
        rows = load_csv()
        LEADERBOARD_MD.write_text(render_md(rows))
        print(f"Regenerated {display_path(LEADERBOARD_MD)} from existing CSV ({len(rows)} rows)")
        return

    if args.target and args.folder:
        print("Error: use either a positional target path or --folder, not both")
        sys.exit(1)

    rows = load_csv()
    row_index_by_log = {r["log_file"]: r for r in rows}

    target = Path(args.folder or args.target or "")
    if not target:
        print("Usage: python scripts/log_result.py [--folder debate_logs] <result.json>")
        sys.exit(1)

    if not target.is_absolute():
        target = REPO_ROOT / target

    if not target.exists():
        print(f"Error: {display_path(target)} not found")
        sys.exit(1)

    try:
        log_paths = collect_log_paths(target)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    if not log_paths:
        print(f"No debate result JSON files found in {target}")
        sys.exit(1)

    changed = False
    added_count = 0
    updated_count = 0
    last_result = None

    for log_path in log_paths:
        with open(log_path) as f:
            data = json.load(f)

        debate_dt = parse_debate_timestamp(log_path.name)
        date_str = debate_dt.strftime("%Y-%m-%d")

        aff_name = data.get("affirmative_name") or data["Affirmative Name"]
        neg_name = data.get("negative_name") or data["Negative Name"]
        material = data["material_name"]
        votes = data["judge_votes"]
        aff_votes = votes.count("affirmative")
        neg_votes = votes.count("negative")
        winner = data["winner"]

        aff_commit = commit_for_file_at(f"students/{aff_name}.py", debate_dt)
        neg_commit = commit_for_file_at(f"students/{neg_name}.py", debate_dt)
        mat_commit = commit_for_file_at(f"materials/{material}", debate_dt)

        if not aff_commit:
            print(f"Warning: could not find commit for students/{aff_name}.py before {debate_dt}")
        if not neg_commit:
            print(f"Warning: could not find commit for students/{neg_name}.py before {debate_dt}")

        perf = extract_perf(data)
        new_row = {
            "date": date_str,
            "affirmative": aff_name,
            "aff_commit": aff_commit,
            "negative": neg_name,
            "neg_commit": neg_commit,
            "material": material,
            "material_commit": mat_commit,
            "log_file": log_path.name,
            "aff_votes": aff_votes,
            "neg_votes": neg_votes,
            "winner": winner,
            **perf,
        }

        last_result = (aff_name, aff_commit, neg_name, neg_commit, aff_votes, neg_votes, winner)

        existing = row_index_by_log.get(log_path.name)
        if existing is not None:
            missing = not all(existing.get(k) for k in ("aff_calls", "neg_calls"))
            if missing:
                existing.update(perf)
                updated_count += 1
                changed = True
            continue

        rows.append(new_row)
        row_index_by_log[log_path.name] = new_row
        added_count += 1
        changed = True

    if changed:
        rows = sort_rows(rows)
        save_csv(rows)
        if added_count:
            print(f"Appended {added_count} new row(s)")
        if updated_count:
            print(f"Updated perf stats for {updated_count} existing row(s)")
    else:
        print("No new rows to add")

    md = render_md(rows)
    LEADERBOARD_MD.write_text(md)
    print(f"Regenerated {display_path(LEADERBOARD_MD)}")

    if len(log_paths) == 1 and last_result is not None:
        aff_name, aff_commit, neg_name, neg_commit, aff_votes, neg_votes, winner = last_result
        print(f"\nResult: {aff_name} ({aff_commit[:7]}) vs {neg_name} ({neg_commit[:7]}) — {aff_votes}-{neg_votes} — winner: {winner}")
    else:
        print(f"Processed {len(log_paths)} log file(s) from {display_path(target)}")


if __name__ == "__main__":
    main()
