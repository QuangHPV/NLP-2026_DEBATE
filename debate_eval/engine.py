from __future__ import annotations

from dataclasses import dataclass
import itertools
import json
from pathlib import Path
import random
from typing import Callable

from .api import DebateHistory, ReadonlyDebateMaterial, ReadonlyDebateTurn, Side, StudentAPI
from .loader import StudentSpeaker
from utils import judge_chat

MAX_SPEECH_CHARS = 7000


@dataclass
class DebateMaterial:
    name: str
    topic: str
    content: str


@dataclass
class DebateTurn:
    round_index: int
    side: str
    speaker: str
    content: str


@dataclass
class DebateAgent:
    name: str
    side: Side
    speak: StudentSpeaker
    api: StudentAPI


def load_materials(materials_dir: str | Path) -> list[DebateMaterial]:
    directory = Path(materials_dir)
    if not directory.exists():
        return []

    materials: list[DebateMaterial] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue

        if path.suffix.lower() in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            topic = lines[0]
            content = "\n".join(lines[1:]) if len(lines) > 1 else lines[0]
            materials.append(DebateMaterial(name=path.name, topic=topic, content=content))
            continue

        if path.suffix.lower() == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw = [raw]
            for index, item in enumerate(raw, start=1):
                topic = item.get("topic", f"{path.stem}-{index}")
                content = item.get("content", "")
                materials.append(
                    DebateMaterial(
                        name=f"{path.name}#{index}",
                        topic=topic,
                        content=content,
                    )
                )
    return materials


def judger(chat_history: list[dict[str, str]], seed: int | None = None) -> str:
    response = judge_chat(chat_history)
    normalized = response.strip().lower()

    if "affirmative" in normalized or "pro" == normalized:
        return "affirmative"
    if "negative" in normalized or "con" == normalized:
        return "negative"

    rng = random.Random(seed)
    return rng.choice(["affirmative", "negative"])


def judge_result(
    chat_history: list[dict[str, str]],
    seed: int | None = None,
) -> tuple[str, str, bool]:
    response = judge_chat(chat_history)
    normalized = response.strip().lower()

    if "affirmative" in normalized or "pro" == normalized:
        return "affirmative", response, False
    if "negative" in normalized or "con" == normalized:
        return "negative", response, False

    rng = random.Random(seed)
    return rng.choice(["affirmative", "negative"]), response, True


class DebateMatch:
    def __init__(
        self,
        affirmative_name: str,
        affirmative_speak: StudentSpeaker,
        negative_name: str,
        negative_speak: StudentSpeaker,
        material: DebateMaterial,
        rounds: int = 5,
        seed: int | None = None,
    ):
        self.material = material
        self.rounds = rounds
        self.seed = seed

        self.affirmative = DebateAgent(
            name=affirmative_name,
            side="affirmative",
            speak=affirmative_speak,
            api=StudentAPI(agent_name=affirmative_name),
        )
        self.negative = DebateAgent(
            name=negative_name,
            side="negative",
            speak=negative_speak,
            api=StudentAPI(agent_name=negative_name),
        )
        self.transcript: list[DebateTurn] = []

    def _readonly_material(self) -> ReadonlyDebateMaterial:
        return ReadonlyDebateMaterial(
            topic=self.material.topic,
            content=self.material.content,
        )

    def _readonly_history(self) -> DebateHistory:
        return tuple(
            ReadonlyDebateTurn(
                round_index=turn.round_index,
                side=turn.side,
                speaker=turn.speaker,
                content=turn.content,
            )
            for turn in self.transcript
        )

    def _judge_history(self) -> list[dict[str, str]]:
        history: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a strict, neutral, professional judge for an English debate match.\n"
                    "Your job is to decide whether the affirmative side or the negative side performed better overall.\n"
                    "Evaluate the full debate using these criteria:\n"
                    "1. Whether each side stays grounded in the motion and the provided material.\n"
                    "2. Whether the reasoning is clear, logical, and persuasive.\n"
                    "3. Whether each side directly answers and effectively rebuts the opponent.\n"
                    "4. Whether the position stays internally consistent without obvious fallacies, evasions, or empty repetition.\n"
                    "5. Which side has the stronger overall clash, defense, and offensive pressure.\n"
                    "Do not reward style, length, or confidence by themselves. Base your judgment only on argumentative quality and debating effectiveness."
                ),
            },
            {
                "role": "user",
                "content": f"Motion: {self.material.topic}\nMaterial: {self.material.content}",
            },
        ]
        for turn in self.transcript:
            history.append(
                {
                    "role": "assistant",
                    "content": f"[{turn.side}] Round {turn.round_index}: {turn.content}",
                }
            )
        history.append(
            {
                "role": "user",
                "content": (
                    "The transcript above is the complete debate.\n"
                    "If the affirmative side performed better overall, output only affirmative.\n"
                    "If the negative side performed better overall, output only negative.\n"
                    "Do not explain your answer. Do not output punctuation, quotes, or any other text."
                ),
            }
        )
        return history

    def _take_turn(
        self,
        agent: DebateAgent,
        round_index: int,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        with agent.api.activate():
            content = agent.speak(
                self._readonly_material(),
                self._readonly_history(),
                agent.side,
            )

        if not isinstance(content, str):
            raise TypeError(f"{agent.name}.speak() must return a string.")

        content = content.strip()
        if not content:
            content = "We have no further additions this round, but we maintain our position."
        if len(content) > MAX_SPEECH_CHARS:
            content = content[:MAX_SPEECH_CHARS].rstrip()
        self.transcript.append(
            DebateTurn(
                round_index=round_index,
                side=agent.side,
                speaker=agent.name,
                content=content,
            )
        )
        if emit is not None:
            emit(f"Round {round_index:02d} [{agent.side}] {agent.name}: {content}")

    def run(self, emit: Callable[[str], None] | None = None) -> dict[str, object]:
        for round_index in range(1, self.rounds + 1):
            self._take_turn(
                self.affirmative,
                round_index=round_index,
                emit=emit,
            )
            self._take_turn(
                self.negative,
                round_index=round_index,
                emit=emit,
            )

        judge_history = self._judge_history()
        winner, judge_raw, judge_fallback = judge_result(judge_history, seed=self.seed)
        if emit is not None:
            visible_judge_raw = judge_raw if judge_raw.strip() else "<empty response>"
            emit(f"Judge raw output: {visible_judge_raw}")
            emit(f"Judge fallback used: {judge_fallback}")
            emit(f"Final winner: {winner}")
        return {
            "topic": self.material.topic,
            "material_name": self.material.name,
            "winner": winner,
            "judge_raw": judge_raw,
            "judge_fallback": judge_fallback,
            "rounds": self.rounds,
            "transcript": [turn.__dict__ for turn in self.transcript],
            "usage": {
                "affirmative": self.affirmative.api.usage.to_dict(),
                "negative": self.negative.api.usage.to_dict(),
            },
        }


def round_robin_pairs(agent_results: list[object]) -> list[tuple[object, object]]:
    return list(itertools.combinations(agent_results, 2))
