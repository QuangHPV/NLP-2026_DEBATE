from __future__ import annotations

import argparse
import json
import random

from .engine import DebateMatch, load_materials, round_robin_pairs
from .loader import discover_student_agents


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Student debate evaluation system")
    parser.add_argument("--students-dir", default="students", help="Directory of student agent files")
    parser.add_argument("--materials-dir", default="materials", help="Directory of debate materials")
    parser.add_argument("--material", default=None, help="Optional material file name to use")
    parser.add_argument("--rounds", type=int, default=10, help="Number of debate rounds")
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

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

    valid_agents = [result for result in discovered if result.is_valid]
    if len(valid_agents) < 2:
        print("Need at least two valid student agents to run a debate.")
        return 1

    materials = _select_materials(args.materials_dir, args.material)
    if not materials:
        print("No debate materials found.")
        return 1

    print("")
    print("Debate results:")
    for material in materials:
        print(f"== Material: {material.name} | Topic: {material.topic} ==")
        for agent_a, agent_b in round_robin_pairs(valid_agents):
            print(f"Matchup: {agent_a.name} (affirmative) vs {agent_b.name} (negative)")
            match = DebateMatch(
                affirmative_cls=agent_a.agent_class,
                negative_cls=agent_b.agent_class,
                material=material,
                rounds=args.rounds,
                seed=args.seed,
            )
            result = match.run(emit=lambda line: print(line, flush=True))
            print(
                f"Summary: {agent_a.name} vs {agent_b.name} | "
                f"winner={result['winner']} | "
                f"judge_raw={json.dumps(result['judge_raw'], ensure_ascii=False)} | "
                f"judge_fallback={result['judge_fallback']} | "
                f"usage={json.dumps(result['usage'], ensure_ascii=False)}"
            )
        print("")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
