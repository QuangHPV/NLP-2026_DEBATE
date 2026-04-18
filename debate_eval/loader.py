from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

from .api import BaseAgent, StudentAPI


@dataclass
class AgentLoadResult:
    name: str
    path: Path
    is_valid: bool
    message: str
    agent_class: type[BaseAgent] | None = None


def _load_module(path: Path) -> ModuleType:
    module_name = f"student_agent_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to create module spec for {path.name}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_agent_class(agent_class: type[BaseAgent]) -> None:
    if not issubclass(agent_class, BaseAgent):
        raise TypeError("Agent must inherit from debate_eval.BaseAgent.")

    argue = getattr(agent_class, "argue", None)
    if argue is None or not callable(argue):
        raise TypeError("Agent must define an argue(chat_history) method.")

    signature = inspect.signature(argue)
    parameters = list(signature.parameters.values())
    if len(parameters) != 2:
        raise TypeError("argue() must accept exactly two parameters: self and chat_history.")


def discover_student_agents(students_dir: str | Path) -> list[AgentLoadResult]:
    directory = Path(students_dir)
    if not directory.exists():
        return []

    results: list[AgentLoadResult] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue

        try:
            module = _load_module(path)
            agent_class = getattr(module, "Agent", None)
            if agent_class is None:
                raise TypeError("Missing Agent class.")

            _validate_agent_class(agent_class)
            agent_class(
                StudentAPI(agent_name=f"validate::{path.stem}"),
                side="affirmative",
                topic="validation topic",
                material="validation material",
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                AgentLoadResult(
                    name=path.stem,
                    path=path,
                    is_valid=False,
                    message=str(exc),
                )
            )
            continue

        results.append(
            AgentLoadResult(
                name=path.stem,
                path=path,
                is_valid=True,
                message="OK",
                agent_class=agent_class,
            )
        )

    return results
