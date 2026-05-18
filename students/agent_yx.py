import re
from debate_eval.api import chat

def _clean_speech(text):
    """
    Bulletproof parser: Strips internal reasoning and meta-tags 
    to guarantee only the final speech is output to the judge.
    """
    text = str(text or "").strip()
    
    # 1. Split based on the hardcoded separator (handles variations in spacing/casing)
    split_match = re.split(r"(?i)={3,}\s*SPEECH\s*={3,}", text)
    if len(split_match) > 1:
        speech = split_match[-1].strip()
    else:
        # Fallback if the LLM used dashes instead of equals
        split_match_alt = re.split(r"(?i)-{3,}\s*SPEECH\s*-{3,}", text)
        if len(split_match_alt) > 1:
            speech = split_match_alt[-1].strip()
        else:
            speech = text.strip()
            
    # 2. Aggressive scrubbing of any residual LLM meta-text or markdown headers
    speech = re.sub(r"(?im)^\s*round\s+\d+.*$", "", speech)
    speech = re.sub(r"(?im)^\s*(affirmative|negative) closing statement.*$", "", speech)
    speech = re.sub(r"^\s*\*\*(Speech|Public Speech|Final Speech)\*\*.*$", "", speech, flags=re.MULTILINE|re.IGNORECASE)
    speech = re.sub(r"^\s*###.*$", "", speech, flags=re.MULTILINE) # Strip leaked markdown headers
    
    # 3. Format cleanup
    speech = re.sub(r"\n{3,}", "\n\n", speech)
    
    # Failsafe character limit to prevent token overflow on the evaluator's end
    return speech.strip()[:6800]


def speak(material, history, side):
    # 1. Calculate debate state
    current_round = (len(history) // 2) + 1
    opponent_side = "negative" if side == "affirmative" else "affirmative"

    # 2. Format the debate history efficiently
    transcript_parts = []
    for turn in history:
        transcript_parts.append(f"Round {turn.round_index} | {turn.side.upper()}:\n{turn.content}")
    transcript = "\n\n".join(transcript_parts) or "No previous turns yet. This is the opening speech."

    # 3. Strategic Pacing
    if current_round == 1:
        round_directive = (
            "ROUND 1 (OPENING): Establish a dominant framework. "
            "Construct 3 heavily grounded offensive pillars using exact facts from the Material. "
            "Preempt the opponent's most likely attack. Open with a strong, authoritative stance."
        )
    elif current_round == 5:
        round_directive = (
            "ROUND 5 (CLOSING): FINAL SPEECH. DO NOT introduce new arguments. "
            "Collapse the entire debate into exactly TWO decisive voting issues. "
            "Show why our side wins these issues using comparative impact weighing and 'Even If' subsumption. "
            "End with a clear, powerful directive to the judge on why to vote for our side."
        )
    else:
        round_directive = (
            f"ROUND {current_round}: MIDDLE GAME. "
            "Dedicate 40% of your speech to ruthlessly dismantling the opponent's last speech. "
            "Attack the causal mechanism of their claims, not just the impact. "
            "Dedicate 60% to advancing our offensive pillars. Capitalize on any arguments the opponent dropped."
        )

    # 4. The Grandmaster Prompt
    system_prompt = (
        "You are an elite, grandmaster-level Debate Agent competing in a strict tournament format. "
        "Your objective is to mathematically dismantle the opponent's logic and persuade the judge using strict material grounding.\n\n"
        "### RULES OF ENGAGEMENT\n"
        "1. STRICT GROUNDING: You may ONLY cite facts, examples, or outcomes explicitly stated in the provided Material. NO external knowledge or hallucinations.\n"
        "2. NO CONCESSIONS BY SILENCE: You must explicitly address the opponent's strongest point from their last turn. Do not let their major claims go unrefuted.\n"
        "3. NO JARGON: Never use explicit debate jargon (e.g., 'strawman', 'ad hominem', 'fallacy'). Explain the logical flaw naturally.\n"
        "4. NO META-TEXT: The public speech must be the exact spoken words. Do not break character. Do not include phrases like 'I need to...', or 'Here is the speech'.\n"
        "5. SIGNPOSTING: Structure your speech clearly (e.g., 'First, regarding the opponent's claim...', 'Second, let us examine...').\n\n"
        "### EXECUTION FORMAT (CRITICAL)\n"
        "You MUST structure your response in exactly two distinct sections separated by the exact string '=== SPEECH ==='.\n\n"
        "=== STRATEGY ===\n"
        "- Quotes to Use: [Extract 2-3 exact quotes from the Material to weaponize]\n"
        "- Opponent's Strongest Point: [Identify it and state your rebuttal mechanism]\n"
        "- Dropped Arguments: [Identify points they ignored to penalize them]\n"
        "=== SPEECH ===\n"
        "[Your final, highly polished 500-750 word public speech. Begin immediately with your opening words. Do not include any headers or bold labels at the top.]"
    )

    user_prompt = (
        f"### MOTION\n{material.topic}\n\n"
        f"### SOURCE MATERIAL (Your only source of truth)\n{material.content}\n\n"
        f"### DEBATE TRANSCRIPT\n{transcript}\n\n"
        f"### YOUR DIRECTIVE\n"
        f"You represent the {side.upper()} side.\n"
        f"{round_directive}\n\n"
        "Output your response starting immediately with === STRATEGY ==="
    )

    # 5. Execution & Failsafes
    try:
        raw_output = chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
        
        final_speech = _clean_speech(raw_output)
        
        # Internal validation to prevent empty returns
        if not final_speech or len(final_speech) < 100:
            raise ValueError("Speech extraction failed or length too short.")
            
        return final_speech
        
    except Exception as e:
        # Absolute Failsafe: Ensures we NEVER time out or crash, guaranteeing a valid response.
        fallback_messages = [
            {"role": "system", "content": "You are a professional debater. Write only the exact public speech text. No headers, no meta-text, no internal thoughts."},
            {"role": "user", "content": f"Write a powerful 450-word debate speech for the {side} side on the motion: {material.topic}. Base it entirely on this material: {material.content}."}
        ]
        return str(chat(fallback_messages)).strip()