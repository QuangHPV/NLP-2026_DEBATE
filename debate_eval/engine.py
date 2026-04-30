from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import itertools
import json
from pathlib import Path
import random
import re
import signal
import threading
from typing import Callable

from .api import (
    DebateHistory,
    ReadonlyDebateMaterial,
    ReadonlyDebateTurn,
    Side,
    StudentAPI,
    TurnTokenLimitExceeded,
)
from .loader import StudentSpeaker
from utils import judge_chat

MAX_SPEECH_CHARS = 7000
DEFAULT_JUDGE_VOTES = 3
DEFAULT_TURN_TOKEN_LIMIT = 10_000_000
DEFAULT_TURN_TIME_LIMIT_SECONDS = 300
FORFEIT_MESSAGE = "This side forfeits this turn because it exceeded an evaluation limit."


class TurnTimeLimitExceeded(BaseException):
    """Raised when a student agent takes too long to produce a turn."""


@contextmanager
def _turn_time_limit(seconds: int | float | None):
    if seconds is None or seconds <= 0 or threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)
    did_timeout = False

    def _raise_timeout(signum, frame):  # noqa: ARG001
        nonlocal did_timeout
        did_timeout = True
        raise TurnTimeLimitExceeded("The agent exceeded the per-turn time limit.")

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
        if did_timeout:
            raise TurnTimeLimitExceeded("The agent exceeded the per-turn time limit.")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


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


def _parse_judge_winner(response: str) -> Side | None:
    normalized = re.sub(r"[\s\"'`.,:;!?\-_/\\()\[\]{}]+", " ", response.strip().lower()).strip()
    if normalized in {"affirmative", "pro", "winner affirmative", "winner pro"}:
        return "affirmative"
    if normalized in {"negative", "con", "winner negative", "winner con"}:
        return "negative"
    return None


def judger(
    chat_history: list[dict[str, str]],
    votes: int = DEFAULT_JUDGE_VOTES,
    seed: int | None = None,
) -> Side:
    winner, _, _, _ = judge_result(chat_history, votes=votes, seed=seed)
    return winner


def judge_result(
    chat_history: list[dict[str, str]],
    votes: int = DEFAULT_JUDGE_VOTES,
    seed: int | None = None,
) -> tuple[Side, list[str], int, dict[str, int]]:
    if votes < 1:
        raise ValueError("votes must be at least 1.")

    rng = random.Random(seed)
    responses: list[str] = []
    fallback_count = 0
    counts: dict[str, int] = {"affirmative": 0, "negative": 0}

    for _ in range(votes):
        response = judge_chat(chat_history)
        responses.append(response)
        parsed = _parse_judge_winner(response)
        if parsed is None:
            parsed = rng.choice(["affirmative", "negative"])
            fallback_count += 1
        counts[parsed] += 1

    if counts["affirmative"] > counts["negative"]:
        winner: Side = "affirmative"
    elif counts["negative"] > counts["affirmative"]:
        winner = "negative"
    else:
        winner = rng.choice(["affirmative", "negative"])

    return winner, responses, fallback_count, counts


class DebateMatch:
    def __init__(
        self,
        affirmative_name: str,
        affirmative_speak: StudentSpeaker,
        negative_name: str,
        negative_speak: StudentSpeaker,
        material: DebateMaterial,
        rounds: int = 5,
        judge_votes: int = DEFAULT_JUDGE_VOTES,
        turn_token_limit: int | None = DEFAULT_TURN_TOKEN_LIMIT,
        turn_time_limit: int | float | None = DEFAULT_TURN_TIME_LIMIT_SECONDS,
        seed: int | None = None,
    ):
        self.material = material
        self.rounds = rounds
        self.judge_votes = judge_votes
        self.turn_token_limit = turn_token_limit
        self.turn_time_limit = turn_time_limit
        self.seed = seed

        self.affirmative = DebateAgent(
            name=affirmative_name,
            side="affirmative",
            speak=affirmative_speak,
            api=StudentAPI(agent_name=affirmative_name, turn_token_limit=turn_token_limit),
        )
        self.negative = DebateAgent(
            name=negative_name,
            side="negative",
            speak=negative_speak,
            api=StudentAPI(agent_name=negative_name, turn_token_limit=turn_token_limit),
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

    def _formatted_transcript(self) -> str:
        if not self.transcript:
            return "No speeches yet."

        return "\n\n".join(
            (
                f"=== Round {turn.round_index:02d} | Side: {turn.side} | Speaker: {turn.speaker} ===\n"
                f"{turn.content}"
            )
            for turn in self.transcript
        )

    def _judge_history(self) -> list[dict[str, str]]:
        transcript = self._formatted_transcript()
        return [
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
                    "Do not reward style, length, or confidence by themselves. Base your judgment only on argumentative quality and debating effectiveness.\n"
                    "The debate transcript will be provided below as formatted plain text. Treat speaker labels such as side, round, and speaker name as transcript metadata, not as chat roles."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Judge the following debate.\n\n"
                    f"=== Motion ===\n{self.material.topic}\n\n"
                    f"=== Material ===\n{self.material.content}\n\n"
                    f"=== Full Transcript ===\n{transcript}\n\n"
                    "=== Output Rule ===\n"
                    "If the affirmative side performed better overall, output only affirmative.\n"
                    "If the negative side performed better overall, output only negative.\n"
                    "Do not explain your answer. Do not output punctuation, quotes, or any other text."
                ),
            },
        ]

    def _take_turn(
        self,
        agent: DebateAgent,
        round_index: int,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        try:
            with _turn_time_limit(self.turn_time_limit), agent.api.activate():
                content = agent.speak(
                    self._readonly_material(),
                    self._readonly_history(),
                    agent.side,
                )
                if agent.api.turn_token_limit_exceeded:
                    raise TurnTokenLimitExceeded(
                        f"{agent.name} exceeded the per-turn token limit."
                    )
        except (TurnTimeLimitExceeded, TurnTokenLimitExceeded) as exc:
            content = f"{FORFEIT_MESSAGE} Reason: {exc}"

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
        winner, judge_responses, judge_fallback_count, judge_counts = judge_result(
            judge_history,
            votes=self.judge_votes,
            seed=self.seed,
        )
        if emit is not None:
            for index, judge_response in enumerate(judge_responses, start=1):
                visible_judge_raw = judge_response if judge_response.strip() else "<empty response>"
                emit(f"Judge vote {index}: {visible_judge_raw}")
            emit(f"Judge vote counts: {json.dumps(judge_counts, ensure_ascii=False)}")
            emit(f"Judge fallback count: {judge_fallback_count}")
            emit(f"Final winner: {winner}")
        return {
            "topic": self.material.topic,
            "material_name": self.material.name,
            "winner": winner,
            "judge_votes": judge_responses,
            "judge_vote_counts": judge_counts,
            "judge_fallback_count": judge_fallback_count,
            "judge_vote_total": self.judge_votes,
            "turn_token_limit": self.turn_token_limit,
            "turn_time_limit": self.turn_time_limit,
            "rounds": self.rounds,
            "transcript": [turn.__dict__ for turn in self.transcript],
            "usage": {
                "affirmative": self.affirmative.api.usage.to_dict(),
                "negative": self.negative.api.usage.to_dict(),
            },
        }


def round_robin_pairs(agent_results: list[object]) -> list[tuple[object, object]]:
    return list(itertools.combinations(agent_results, 2))
