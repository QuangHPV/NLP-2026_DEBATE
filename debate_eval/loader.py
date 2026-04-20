from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType
from typing import Callable

from .api import DebateHistory, ReadonlyDebateMaterial, Side


StudentSpeaker = Callable[[ReadonlyDebateMaterial, DebateHistory, Side], str]


@dataclass
class AgentLoadResult:
    name: str
    path: Path
    is_valid: bool
    message: str
    speak_function: StudentSpeaker | None = None


def _load_module(path: Path) -> ModuleType:
    module_name = f"student_agent_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to create module spec for {path.name}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_speak_function(speak: StudentSpeaker) -> None:
    if not callable(speak):
        raise TypeError("speak must be callable.")

    signature = inspect.signature(speak)
    parameters = list(signature.parameters.values())
    if len(parameters) != 3:
        raise TypeError(
            "speak() must accept exactly three parameters: material, history, side."
        )


def load_student_agent(path: str | Path) -> AgentLoadResult:
    student_path = Path(path)
    try:
        if not student_path.exists():
            raise FileNotFoundError(f"Student file not found: {student_path}")
        if not student_path.is_file():
            raise TypeError(f"Student path is not a file: {student_path}")
        if student_path.suffix != ".py":
            raise TypeError(f"Student file must be a .py file: {student_path}")

        module = _load_module(student_path)
        speak = getattr(module, "speak", None)
        if speak is None:
            raise TypeError("Missing speak(material, history, side) function.")

        _validate_speak_function(speak)
    except Exception as exc:  # noqa: BLE001
        return AgentLoadResult(
            name=student_path.stem,
            path=student_path,
            is_valid=False,
            message=str(exc),
        )

    return AgentLoadResult(
        name=student_path.stem,
        path=student_path,
        is_valid=True,
        message="OK",
        speak_function=speak,
    )


def discover_student_agents(students_dir: str | Path) -> list[AgentLoadResult]:
    directory = Path(students_dir)
    if not directory.exists():
        return []

    results: list[AgentLoadResult] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue

        results.append(load_student_agent(path))

    return results
