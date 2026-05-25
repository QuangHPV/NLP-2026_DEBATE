#!/usr/bin/env python3
"""
log_result.py — Record a debate result into leaderboard.csv and regenerate LEADERBOARD.md.

Usage:
    python scripts/log_result.py debate_logs/<result_file>.json

Workflow:
    1. Run a debate.
    2. Run this script on the resulting log file.
    3. Review the appended row in leaderboard.csv.
    4. Commit: git add debate_logs/ leaderboard.csv LEADERBOARD.md && git commit
"""

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
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.json$", log_filename)
    if not m:
        raise ValueError(f"Cannot parse timestamp from filename: {log_filename}")
    date_str, time_str = m.group(1), m.group(2).replace("-", ":")
    tz = timezone(TZ_OFFSET)
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)


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


def save_csv(rows):
    with open(LEADERBOARD_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


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
    # --regen: skip CSV append and just regenerate LEADERBOARD.md from existing CSV
    if "--regen" in sys.argv:
        rows = load_csv()
        LEADERBOARD_MD.write_text(render_md(rows))
        print(f"Regenerated {LEADERBOARD_MD} from existing CSV ({len(rows)} rows)")
        return

    if len(sys.argv) != 2:
        print("Usage: python scripts/log_result.py debate_logs/<result>.json [--regen]")
        sys.exit(1)

    log_path = Path(sys.argv[1])
    if not log_path.is_absolute():
        log_path = REPO_ROOT / log_path

    if not log_path.exists():
        print(f"Error: {log_path} not found")
        sys.exit(1)

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

    rows = load_csv()

    existing = next((r for r in rows if r["log_file"] == log_path.name), None)
    if existing is not None:
        # Update perf stats if any of the new columns are missing in the stored row
        missing = not all(existing.get(k) for k in ("aff_calls", "neg_calls"))
        if missing:
            existing.update(perf)
            save_csv(rows)
            print(f"Updated perf stats for existing row: {log_path.name}")
        else:
            print(f"Row for {log_path.name} already complete — skipping.")
    else:
        rows.append(new_row)
        save_csv(rows)
        print(f"Appended row for {log_path.name}")

    md = render_md(rows)
    LEADERBOARD_MD.write_text(md)
    print(f"Regenerated {LEADERBOARD_MD}")
    print(f"\nResult: {aff_name} ({aff_commit[:7]}) vs {neg_name} ({neg_commit[:7]}) — {aff_votes}-{neg_votes} — winner: {winner}")


if __name__ == "__main__":
    main()
