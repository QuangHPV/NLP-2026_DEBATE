# English Debate Agent Starter

This repository is a starter framework for building and testing Python agents for an English-language debate match. Your job as a student is to implement one function, test it locally, and iterate until your agent can debate well on unseen materials.

The current evaluation setting uses 5 rounds per side, which means 10 total speeches in one match.

## What You Build

Each student submission is a Python file in `students/` that defines:

```python
def speak(material, history, side) -> str:
    ...
```

The evaluator calls `speak(...)` once per turn. Your function receives:

- `material`
  - A read-only object with `material.topic` and `material.content`
- `history`
  - A read-only tuple of all previous turns
- `side`
  - Either `"affirmative"` or `"negative"`

Your function must return the current speech as a string.

Each single returned speech is capped at 7,000 characters by the evaluator. If your function returns more than 7,000 characters, the engine truncates it before storing and judging the turn.

## Quick Start

1. Clone the repository and enter it.

```bash
git clone <your-course-repo-url>
cd NLP@2026
```

2. Create your own working branch.

```bash
git checkout -b your-name-agent
```

3. Copy one of the example agents and start editing it.

```bash
cp students/example_attack.py students/your_agent.py
```

4. Validate your file.

```bash
python -m debate_eval.cli --affirmative-file students/your_agent.py --negative-file students/example_balanced.py --validate-only
```

5. Run a real test match.

```bash
python -m debate_eval.cli --affirmative-file students/your_agent.py --negative-file students/example_balanced.py --material real_material_001.txt --rounds 5
```

## Repository Layout

```text
NLP@2026/
├── debate_eval/
│   ├── api.py          # Student-facing helper functions and readonly types
│   ├── cli.py          # Command-line entrypoint
│   ├── engine.py       # Debate runner and judge prompt
│   └── loader.py       # Student file loading and validation
├── materials/          # Debate materials used for evaluation
├── students/           # Your agent file lives here
├── gen_materials.py    # Optional script to generate more materials
├── utils.py            # Actual model/API calls
└── README.md
```

## Student API

You are expected to implement your logic inside `speak(material, history, side)`.

The student-facing helper functions are intentionally minimal:

- `debate_eval.api.chat(messages) -> str`
- `debate_eval.api.forward(messages, content, role="user") -> list[dict[str, str]]`
- `debate_eval.api.generate(messages) -> str`

Right now `generate(messages)` is just an alias for `chat(messages)`, but it is kept for compatibility.

### Minimal Example

```python
from debate_eval.api import chat


def speak(material, history, side):
    transcript = "\n".join(
        f"Round {turn.round_index} {turn.side}: {turn.content}" for turn in history
    ) or "No previous turns yet."

    messages = [
        {
            "role": "system",
            "content": f"You are an English debater speaking for the {side} side.",
        },
        {
            "role": "user",
            "content": (
                f"Motion: {material.topic}\n"
                f"Material: {material.content}\n"
                f"Transcript:\n{transcript}\n"
                "Give the next speech for your side in English."
            ),
        },
    ]
    return chat(messages)
```

### Multi-Step Agent Pattern

You are allowed to call `chat(...)` multiple times inside one turn. For example:

1. Summarize the most important conflict in the material.
2. Identify the opponent's strongest recent claim.
3. Draft a rebuttal.
4. Produce the final speech.

This is a good fit if you want your agent to behave like a small reasoning system instead of a single prompt.

Example skeleton:

```python
from debate_eval.api import chat, forward


def speak(material, history, side):
    transcript = "\n".join(
        f"Round {turn.round_index} {turn.side}: {turn.content}" for turn in history
    ) or "No previous turns yet."

    base = [
        {
            "role": "system",
            "content": f"You are an English debater on the {side} side.",
        }
    ]
    base = forward(base, f"Motion: {material.topic}")
    base = forward(base, f"Material: {material.content}")
    base = forward(base, f"Transcript:\n{transcript}")

    plan = chat(forward(base, "List the two highest-priority points I should make next."))
    final_messages = forward(base, f"Here is my planning note: {plan}")
    final_messages = forward(final_messages, "Now write the actual speech in English.")
    return chat(final_messages)
```

## Development Advice

- Read the whole material. The evaluation materials are designed so that shallow keyword matching is not enough.
- Use the transcript. Strong agents answer what the opponent actually said instead of repeating prewritten points.
- Keep the side stable. Your agent should never switch from affirmative to negative or vice versa mid-debate.
- Prefer argument quality over verbosity. The judge prompt rewards relevance, logic, rebuttal quality, and consistency.
- Keep each speech within 7,000 characters. Longer outputs will be truncated by the evaluator.
- Handle the first turn gracefully. `history` may be empty.
- Return plain text. Do not return JSON unless your own pipeline needs it internally and you convert it back before returning.

## Validation Rules

Your file must:

1. Live in `students/`
2. Be a `.py` file
3. Define `speak(material, history, side)`
4. Return a string when called by the engine

If any of these fail, the CLI will mark the file as `INVALID`.

## Testing Commands

### Validate all student files in `students/`

```bash
python -m debate_eval.cli --validate-only
```

### Validate one specific matchup

```bash
python -m debate_eval.cli \
  --affirmative-file students/your_agent.py \
  --negative-file students/example_balanced.py \
  --validate-only
```

### Run one specific matchup on one specific material

```bash
python -m debate_eval.cli \
  --affirmative-file students/your_agent.py \
  --negative-file students/example_balanced.py \
  --material real_material_001.txt \
  --rounds 5
```

The default setting is also 5 rounds per side, so if you omit `--rounds`, one match will still contain 10 total speeches.

### Fix randomness for reproducibility

```bash
python -m debate_eval.cli --seed 7
```

The seed affects:

- Random material selection when `--material` is omitted
- Random fallback if the judge returns an unparsable answer

## Material Format

Files in `materials/` may be `.txt`, `.md`, or `.json`.

For `.txt` and `.md`:

- Line 1 is the motion
- The remaining lines are the material body

Example:

```text
AI grading should replace part of the routine assessment workload in universities.
Supporters may emphasize speed, consistency, and scalability. Opponents may emphasize pedagogy, accountability, and the loss of teacher judgment.
```

For `.json`:

- A single object or a list of objects is accepted
- Each object should usually contain `topic` and `content`

## Generating More Debate Materials

You can generate new English materials with:

```bash
python gen_materials.py --prompt "Create debate materials about education policy, platform governance, and long-term social mobility." --count 3
```

This writes new files into `materials/` by default.

## What the Judge Looks For

The built-in judge compares both sides on:

- Relevance to the motion and the material
- Clarity and logic
- Direct rebuttal quality
- Consistency
- Overall clash quality

The judge is instructed to output only:

- `affirmative`
- `negative`

## Evaluation Constraints

- The standard evaluation setup uses 5 rounds per side.
- That means one match contains 10 total speeches.
- Each individual speech is limited to 7,000 characters after the engine receives it.

## Suggested Workflow for a Student

1. Start from `students/example_attack.py` or `students/example_balanced.py`.
2. Get a minimal version running first.
3. Validate your file.
4. Run short matches on one material.
5. Improve your prompting or multi-step pipeline.
6. Test against several opponents and several materials.
7. Commit your work once your agent is stable.

## Git Tips

A simple workflow is:

```bash
git status
git add students/your_agent.py
git commit -m "Build first working debate agent"
```

If your course expects pull requests, push your branch and open one according to your class instructions.

## Important Notes

- The actual model/API configuration lives in `utils.py`.
- If you want to change debate rules, judging behavior, or match flow, look in `debate_eval/engine.py`.
- If you want to change how student files are loaded or validated, look in `debate_eval/loader.py`.
- If you only want to build your own agent, you usually only need to edit files under `students/`.
