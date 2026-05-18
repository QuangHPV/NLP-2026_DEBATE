from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import random

from .engine import (
    DEFAULT_JUDGE_VOTES,
    DEFAULT_TURN_TIME_LIMIT_SECONDS,
    DEFAULT_TURN_TOKEN_LIMIT,
    DebateMatch,
    load_materials,
    round_robin_pairs,
)
from .loader import AgentLoadResult, discover_student_agents, load_student_agent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Student debate evaluation system")
    parser.add_argument("--students-dir", default="students", help="Directory of student agent files")
    parser.add_argument(
        "--affirmative-file",
        default=None,
        help="Specific student file to use as the affirmative side",
    )
    parser.add_argument(
        "--negative-file",
        default=None,
        help="Specific student file to use as the negative side",
    )
    parser.add_argument("--materials-dir", default="materials", help="Directory of debate materials")
    parser.add_argument("--material", default=None, help="Optional material file name to use")
    parser.add_argument(
        "--rounds",
        type=int,
        default=5,
        help="Number of debate rounds per side; default is 5 rounds (10 total speeches)",
    )
    parser.add_argument(
        "--judge-votes",
        type=int,
        default=DEFAULT_JUDGE_VOTES,
        help="Number of independent judge votes to aggregate; default is 3.",
    )
    parser.add_argument(
        "--turn-token-limit",
        type=int,
        default=DEFAULT_TURN_TOKEN_LIMIT,
        help="Per-turn token budget for each student agent; default is 10000000.",
    )
    parser.add_argument(
        "--turn-time-limit",
        type=float,
        default=DEFAULT_TURN_TIME_LIMIT_SECONDS,
        help="Per-turn time limit in seconds; default is 300. Use 0 to disable.",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for judger")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate student agent files and exit",
    )
    return parser


def _select_materials(materials_dir: str, material_name: str | None):
    materials = load_materials(materials_dir)
    if not materials:
        return []
    if material_name is None:
        return [random.choice(materials)]
    return [material for material in materials if material.name == material_name]


def _resolve_student_path(students_dir: str, file_value: str) -> Path:
    raw_path = Path(file_value)
    if raw_path.is_absolute():
        return raw_path

    direct = Path(file_value)
    if direct.exists():
        return direct

    return Path(students_dir) / file_value


def _load_requested_agents(args: argparse.Namespace) -> list[AgentLoadResult]:
    affirmative_path = _resolve_student_path(args.students_dir, args.affirmative_file)
    negative_path = _resolve_student_path(args.students_dir, args.negative_file)
    return [
        load_student_agent(affirmative_path),
        load_student_agent(negative_path),
    ]


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    requested_matchup = args.affirmative_file is not None or args.negative_file is not None
    if requested_matchup and (args.affirmative_file is None or args.negative_file is None):
        print("Must provide both --affirmative-file and --negative-file.")
        return 1

    if requested_matchup:
        discovered = _load_requested_agents(args)
    else:
        discovered = discover_student_agents(args.students_dir)
    if not discovered:
        print("No student agents found.")
        return 1

    print("Validation results:")
    for result in discovered:
        status = "VALID" if result.is_valid else "INVALID"
        print(f"- {result.name}: {status} ({result.message})")

    if args.validate_only:
        return 0

    if requested_matchup:
        if not all(result.is_valid for result in discovered):
            print("The specified affirmative and negative student files must both be valid.")
            return 1
        matchups = [(discovered[0], discovered[1])]
    else:
        valid_agents = [result for result in discovered if result.is_valid]
        if len(valid_agents) < 2:
            print("Need at least two valid student agents to run a debate.")
            return 1
        matchups = round_robin_pairs(valid_agents)

    materials = _select_materials(args.materials_dir, args.material)
    if not materials:
        print("No debate materials found.")
        return 1

    print("")
    print("Debate results:")
    for material in materials:
        print(f"== Material: {material.name} | Topic: {material.topic} ==")
        for agent_a, agent_b in matchups:
            if agent_a.speak_function is None or agent_b.speak_function is None:
                continue

            print(f"Matchup: {agent_a.name} (affirmative) vs {agent_b.name} (negative)")
            match = DebateMatch(
                affirmative_name=agent_a.name,
                affirmative_speak=agent_a.speak_function,
                negative_name=agent_b.name,
                negative_speak=agent_b.speak_function,
                material=material,
                rounds=args.rounds,
                judge_votes=args.judge_votes,
                turn_token_limit=args.turn_token_limit if args.turn_token_limit > 0 else None,
                turn_time_limit=args.turn_time_limit if args.turn_time_limit > 0 else None,
                seed=args.seed,
            )
            result = match.run(emit=lambda line: print(line, flush=True))
            print(
                f"Summary: {agent_a.name} vs {agent_b.name} | "
                f"winner={result['winner']} | "
                f"judge_votes={json.dumps(result['judge_votes'], ensure_ascii=False)} | "
                f"judge_vote_counts={json.dumps(result['judge_vote_counts'], ensure_ascii=False)} | "
                f"judge_fallback_count={result['judge_fallback_count']} | "
                f"turn_token_limit={result['turn_token_limit']} | "
                f"turn_time_limit={result['turn_time_limit']} | "
                f"usage={json.dumps(result['usage'], ensure_ascii=False)}"
            )
            # log stat_summary to a file with timestamp and agent names
            stat_summary = {
                "Affirmative Name": agent_a.name,
                "Negative Name": agent_b.name
            }
            stat_summary.update(result)
            log_dir = Path("debate_logs")
            log_dir.mkdir(exist_ok=True)
            log_filename = f"debate_result_{agent_a.name}_vs_{agent_b.name}_{material.name}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
            log_filepath = os.path.join(log_dir, log_filename)
            with open(log_filepath, "w") as f:
                json.dump(stat_summary, f, indent=2)
                print(f"Saved debate result to {log_filepath}")
        print("")

    return stat_summary


if __name__ == "__main__":
    raise SystemExit(main())
