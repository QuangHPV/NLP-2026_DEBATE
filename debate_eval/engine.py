from __future__ import annotations

from dataclasses import dataclass
import itertools
import json
from pathlib import Path
import random
from typing import Callable

from .api import BaseAgent, ChatTemplate, StudentAPI
from utils import judge_chat


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


def judger(chat_history: ChatTemplate, seed: int | None = None) -> str:
    response = judge_chat(chat_history)
    normalized = response.strip().lower()

    if "affirmative" in normalized or "正方" in response:
        return "affirmative"
    if "negative" in normalized or "反方" in response:
        return "negative"

    rng = random.Random(seed)
    return rng.choice(["affirmative", "negative"])


def judge_result(chat_history: ChatTemplate, seed: int | None = None) -> tuple[str, str, bool]:
    response = judge_chat(chat_history)
    normalized = response.strip().lower()

    if "affirmative" in normalized or "正方" in response:
        return "affirmative", response, False
    if "negative" in normalized or "反方" in response:
        return "negative", response, False

    rng = random.Random(seed)
    return rng.choice(["affirmative", "negative"]), response, True


class DebateMatch:
    def __init__(
        self,
        affirmative_cls: type[BaseAgent],
        negative_cls: type[BaseAgent],
        material: DebateMaterial,
        rounds: int = 10,
        seed: int | None = None,
    ):
        self.material = material
        self.rounds = rounds
        self.seed = seed

        self.affirmative_api = StudentAPI(agent_name=affirmative_cls.__name__)
        self.negative_api = StudentAPI(agent_name=negative_cls.__name__)
        self.affirmative = affirmative_cls(
            api=self.affirmative_api,
            side="affirmative",
            topic=material.topic,
            material=material.content,
        )
        self.negative = negative_cls(
            api=self.negative_api,
            side="negative",
            topic=material.topic,
            material=material.content,
        )
        self.transcript: list[DebateTurn] = []

    def _system_prompt(self, side: str) -> str:
        return (
            f"你正在参加辩论赛，立场是 {side}。\n"
            f"辩题：{self.material.topic}\n"
            f"材料：{self.material.content}\n"
            "请每次只输出一句清晰的辩论发言。"
        )

    def _chat_history_for(self, side: str) -> ChatTemplate:
        history: ChatTemplate = [{"role": "system", "content": self._system_prompt(side)}]
        for turn in self.transcript:
            role = "assistant" if turn.side == side else "user"
            history.append(
                {
                    "role": role,
                    "content": f"第{turn.round_index}轮 {turn.side}: {turn.content}",
                }
            )
        return history

    def _judge_history(self) -> ChatTemplate:
        history: ChatTemplate = [
            {
                "role": "system",
                "content": (
                    "你是一名严格、中立、专业的中文辩论赛裁判。\n"
                    "你的任务是根据完整辩论过程，公平判断正方（affirmative）或反方（negative）谁的整体表现更强。\n"
                    "请重点考察以下标准：\n"
                    "1. 论点是否紧扣辩题与给定材料；\n"
                    "2. 论证是否清晰、有逻辑、有说服力；\n"
                    "3. 是否正面回应并有效反驳对方观点；\n"
                    "4. 立场是否前后一致，是否出现明显漏洞、偷换概念或重复空话；\n"
                    "5. 整体攻防质量谁更占优。\n"
                    "不要因为措辞华丽、篇幅长短或语气强烈而偏袒任何一方，必须以论证质量和攻防效果为唯一依据。"
                ),
            },
            {
                "role": "user",
                "content": f"辩题：{self.material.topic}\n材料：{self.material.content}",
            },
        ]
        for turn in self.transcript:
            history.append(
                {
                    "role": "assistant",
                    "content": f"[{turn.side}] 第{turn.round_index}轮：{turn.content}",
                }
            )
        history.append(
            {
                "role": "user",
                "content": (
                    "以上是完整辩论记录。现在请你作为裁判，严格依据辩论内容公平裁定胜负。\n"
                    "如果正方整体更强，只输出 affirmative。\n"
                    "如果反方整体更强，只输出 negative。\n"
                    "不要解释理由，不要输出标点、换行或其他任何内容。"
                ),
            }
        )
        return history

    def _take_turn(
        self,
        agent: BaseAgent,
        speaker_name: str,
        round_index: int,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        history = self._chat_history_for(agent.side)
        content = agent.argue(history).strip()
        if not content:
            content = "我方暂无更多补充，但坚持既有立场。"
        self.transcript.append(
            DebateTurn(
                round_index=round_index,
                side=agent.side,
                speaker=speaker_name,
                content=content,
            )
        )
        if emit is not None:
            emit(f"Round {round_index:02d} [{agent.side}] {speaker_name}: {content}")

    def run(self, emit: Callable[[str], None] | None = None) -> dict[str, object]:
        for round_index in range(1, self.rounds + 1):
            self._take_turn(
                self.affirmative,
                speaker_name="affirmative",
                round_index=round_index,
                emit=emit,
            )
            self._take_turn(
                self.negative,
                speaker_name="negative",
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
                "affirmative": self.affirmative_api.usage.to_dict(),
                "negative": self.negative_api.usage.to_dict(),
            },
        }


def round_robin_pairs(agent_results: list[object]) -> list[tuple[object, object]]:
    return list(itertools.combinations(agent_results, 2))
