from debate_eval.api import chat

def speak(material, history, side):
    # 1. Calculate where we are in the debate to prevent the looping bug
    # Since each round has 2 speeches, integer division by 2 gives us the completed rounds
    current_round = (len(history) // 2) + 1
    opponent_side = "negative" if side == "affirmative" else "affirmative"

    # 2. Format the debate history
    transcript = "\n".join(
        f"Round {turn.round_index} {turn.side}: {turn.content}" for turn in history
    ) or "No previous turns yet."

    shared_context = (
        f"Motion: {material.topic}\n\n"
        f"Material:\n{material.content}\n\n"
        f"Transcript so far:\n{transcript}"
    )

    # -------------------------------------------------------------------------
    # STEP 1: The Logical Fallacy Hunt (Hidden from the Judge)
    # -------------------------------------------------------------------------
    if len(history) == 0:
        # If we are the Affirmative speaking first, there is no opponent to analyze yet.
        fallacy_analysis = "This is the opening speech. We must establish the core logical framework of our case."
    else:
        # Extract exactly what the opponent just said
        last_opponent_speech = history[-1].content
        
        analysis_messages = [
            {
                "role": "system",
                "content": "You are a master debate strategist and logician."
            },
            {
                "role": "user",
                "content": (
                    f"{shared_context}\n\n"
                    f"The opponent ({opponent_side}) just gave this speech:\n'{last_opponent_speech}'\n\n"
                    "Analyze the opponent's last speech closely. Hunt for any logical fallacies "
                    "(e.g., strawman, false dichotomy, slippery slope, post hoc, ad hominem) or unsupported claims. "
                    "Output a concise, 3-bullet-point summary of their weakest logical links that we must dismantle. "
                    "Be highly critical but strictly analytical."
                ),
            },
        ]
        # Call the LLM to generate the analysis (this uses tokens but is not seen by the judge)
        fallacy_analysis = chat(analysis_messages)

    # -------------------------------------------------------------------------
    # STEP 2: Drafting the Final Speech
    # -------------------------------------------------------------------------
    
    # Adjust instructions based on whether we are opening, continuing, or closing
    if current_round == 1:
        pacing_instruction = "This is your opening speech. Establish our foundational arguments clearly and preemptively inoculate against obvious counterarguments."
    elif current_round == 5:
        pacing_instruction = "This is Round 5, your FINAL closing speech. DO NOT introduce new points. Summarize the debate, weigh the core clashes, and demonstrate why our logic prevails."
    else:
        pacing_instruction = f"This is Round {current_round} out of 5. Introduce your next constructive argument while directly rebutting the opponent's fallacies."

    draft_messages = [
        {
            "role": "system",
            "content": (
                f"You are a highly skilled English debater representing the {side} side. "
                "Your tone MUST be academic, measured, and diplomatic. Rely strictly on logic and the provided material. "
                "Do not use highly aggressive, emotional, or combative language. Maintain professional decorum while systematically dismantling the opponent's arguments."
                "Never dilute or apologize for the core motion. If the motion is an absolute mandate, defend the mandate aggressively. Do not add hypothetical conditions to make the policy sound easier."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{shared_context}\n\n"
                f"--- OUR STRATEGIC ANALYSIS OF THE OPPONENT ---\n{fallacy_analysis}\n\n"
                f"--- INSTRUCTIONS FOR THIS SPEECH ---\n"
                f"{pacing_instruction}\n\n"
                "Write the full speech in English. \n"
                "IMPORTANT: DO NOT output any meta-text, round numbers, or headers (e.g., do not start with 'Speech 3:' or 'Round 3:'). "
                "Write a highly polished, grammatically perfect speech. Limit your response to exactly 800 words to ensure maximum impact and clarity."
            ),
        },
    ]

    # Call the LLM one final time to draft the speech to return to the engine
    return chat(draft_messages)