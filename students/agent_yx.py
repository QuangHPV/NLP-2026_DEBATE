from debate_eval.api import chat

def speak(material, history, side):
    # 1. Calculate where we are in the debate to prevent the looping bug
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
        fallacy_analysis = "This is the opening speech. We must establish the core logical framework of our case."
    else:
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
        fallacy_analysis = chat(analysis_messages)

    # -------------------------------------------------------------------------
    # STEP 1.5: The Researcher (Evidence Extraction)
    # -------------------------------------------------------------------------
    research_messages = [
        {
            "role": "system",
            "content": "You are an elite debate researcher. Your job is to mine the background material for hard evidence."
        },
        {
            "role": "user",
            "content": (
                f"Motion: {material.topic}\n\n"
                f"Material:\n{material.content}\n\n"
                f"--- OUR OPPONENT'S WEAKNESSES ---\n{fallacy_analysis}\n\n"
                f"Based on the weaknesses identified above, scan the Material and extract 2 or 3 SPECIFIC facts, statistics, or direct quotes that we can use to destroy the opponent's logic and support our {side} case in Round {current_round}. "
                "Output only a bulleted list of the exact evidence we should use."
            )
        }
    ]
    
    # Call the LLM to extract hard evidence (Hidden from the judge)
    research_notes = chat(research_messages)

    # -------------------------------------------------------------------------
    # STEP 2: Drafting the Initial Speech
    # -------------------------------------------------------------------------
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
                "Do not use highly aggressive, emotional, or combative language. Maintain professional decorum while systematically dismantling the opponent's arguments. "
                "Never dilute or apologize for the core motion. If the motion is an absolute mandate, defend the mandate aggressively. "
                "CRITICAL STRATEGY: When attacking the opponent's logic, NEVER explicitly use academic fallacy terms like 'strawman', 'false dichotomy', 'hasty generalization', or 'ad hominem'. Explain *why* their logic is broken naturally and conversationally."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{shared_context}\n\n"
                f"--- OUR STRATEGIC ANALYSIS OF THE OPPONENT ---\n{fallacy_analysis}\n\n"
                f"--- HARD EVIDENCE TO CITE ---\n{research_notes}\n\n"
                f"--- INSTRUCTIONS FOR THIS SPEECH ---\n"
                f"{pacing_instruction}\n\n"
                "Write the full speech in English. \n"
                "IMPORTANT: DO NOT output any meta-text, round numbers, or headers. "
                "Write a highly polished, grammatically perfect speech. Limit your response to exactly 800 words to ensure maximum impact and clarity. "
                "You MUST seamlessly weave the 'Hard Evidence' provided above into your arguments."
            ),
        }
    ]

    draft_speech = chat(draft_messages)

    # -------------------------------------------------------------------------
    # STEP 3: The Validation & Refinement Pass (New Critic Step)
    # -------------------------------------------------------------------------
    validation_messages = [
        {
            "role": "system",
            "content": (
                "You are an elite debate coach and rigorous copy editor. Your job is to review a drafted debate speech, "
                "fix any grammatical errors, elevate the prose, and ensure strict adherence to strategic constraints."
            )
        },
        {
            "role": "user",
            "content": (
                f"Here is the drafted speech for our {side} side in Round {current_round}:\n\n"
                f"<draft>\n{draft_speech}\n</draft>\n\n"
                "Please review and refine this speech based on these CRITICAL rules:\n"
                "1. Fix any broken grammar, typos, or degraded formatting.\n"
                "2. Ensure the tone is flawlessly academic and diplomatic.\n"
                "3. Ensure the speaker defends the absolute mandate of the motion and does not concede ground with weak hypotheticals.\n"
                "4. Strip out any meta-text like 'Here is the improved speech:' or 'Round 3:'.\n"
                "5. Ensure the final length is comfortably under 800 words.\n"
                "6. JARGON CHECK: If the draft uses explicit academic fallacy terms (e.g., 'strawman', 'false dichotomy', 'hasty generalization', 'ad hominem', 'slippery slope'), you MUST rewrite those sentences to explain the logical flaw naturally without using the jargon. Make it sound conversational.\n\n"
                "Output ONLY the final, polished words that will be spoken to the judge. Nothing else."
            )
        }
    ]

    return chat(validation_messages)