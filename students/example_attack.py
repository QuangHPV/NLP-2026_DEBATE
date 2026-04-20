from debate_eval.api import chat


def speak(material, history, side):
    transcript = "\n".join(
        f"Round {turn.round_index} {turn.side}: {turn.content}" for turn in history
    ) or "No previous turns yet."
    return chat(
        [
            {
                "role": "system",
                "content": (
                    "You are an English debate speaker. "
                    f"Your current side is {side}. "
                    "Continue the debate using the motion, the material, and the transcript so far. "
                    "Keep the speech within 7000 characters."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Motion: {material.topic}\n"
                    f"Material: {material.content}\n"
                    f"Transcript so far:\n{transcript}\n"
                    "Reply with the current speech for your side in English, staying within 7000 characters."
                ),
            },
        ]
    )
