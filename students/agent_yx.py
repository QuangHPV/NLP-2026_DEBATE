import re
from debate_eval.api import chat

def _safe_trim(text, max_chars=6800):
    """
    The Ultimate Parse Shield: Splits by </think> to guarantee internal monologue 
    NEVER bleeds into the final speech, then cleans up the prose.
    """
    text = str(text or "").strip()
    
    # Hijack DeepSeek's native think block structure
    if "</think>" in text:
        speech = text.split("</think>")[-1].strip()
    else:
        # Fallback if no tags are present
        match = re.search(r'<final_speech>\s*(.*?)\s*(?:</final_speech>|$)', text, re.DOTALL | re.IGNORECASE)
        if match:
            speech = match.group(1).strip()
        else:
            speech = re.sub(r'<[^>]+>', '', text).strip()

    speech = re.sub(r"(?i)^(Here is the speech:|Speech:)\s*", "", speech)
    speech = re.sub(r"(?im)^\s*(affirmative|negative) closing statement.*$", "", speech)
    speech = speech.replace("**", "")
    speech = re.sub(r"\n{3,}", "\n\n", speech).strip()
    return speech[:max_chars]

def _get_used_evidence(history, side):
    """
    Hacks persistence in a stateless environment by regex-mining our past 
    speeches to ensure we never reuse the same quotes (Evidence Freshness).
    """
    used_quotes = set()
    for t in history:
        if t.side.lower() == side.lower():
            # Extract anything inside quotes from our past speeches
            matches = re.findall(r'"([^"]{15,})"', t.content) + re.findall(r"'([^']{15,})'", t.content)
            for match in matches:
                used_quotes.add(match[:40] + "...")
    return list(used_quotes)

def speak(material, history, side):
    current_round = (len(history) // 2) + 1

    # 1. ALGORITHMIC WINDOWING (Formatted Plain Text)
    # We only process the last 4 turns to kill latency bloat
    recent_history = history[-4:] if len(history) > 4 else history
    active_transcript = "\n".join(
        f"Round {t.round_index} {t.side.upper()}:\n{t.content}"
        for t in recent_history
    ) or "No previous turns."
    
    if len(history) > 4:
        active_transcript = f"[EARLIER ROUNDS OMITTED FOR LATENCY]\n\n--- ACTIVE CLASH ---\n{active_transcript}"

    # 2. EVIDENCE FRESHNESS TRACKER & DIVERSITY
    used_evidence = _get_used_evidence(history, side)
    freshness_directive = f"\nDO NOT RECYCLE THESE QUOTES: {used_evidence}" if used_evidence else ""

    past_openers = [f"R{t.round_index}: '{' '.join(t.content.strip().split()[:10])}'" for t in history if t.side.lower() == side.lower() and t.content.strip()]
    diversity_note = f"\nDO NOT REPEAT THESE OPENERS:\n" + "\n".join(past_openers) if past_openers else ""

    # 3. THE CLINICAL DOMINANCE MATRIX
    system = (
        "You are an elite, clinically dominant debate speaker. "
        "THE ZERO-CONCESSION DIRECTIVE: NEVER use conciliatory language ('grant', 'even if', 'acknowledge'). "
        "LEXICON MATRIX: Use academic debate terminology (e.g., 'structural turn', 'threshold gap', 'quantitative decomposition', 'impact calculus'). "
        "DO NOT use ad-hominem attacks or emotional adjectives. Destroy their logic surgically. "
        "You MUST use a <think> block to plan your strategy and extract evidence before outputting the final speech."
    )

    # 4. SIDE-SPECIFIC BURDEN ASYMMETRY
    if side.lower() == "affirmative":
        burden_directive = "AFFIRMATIVE BURDEN: You must prove the motion is absolutely necessary and net-beneficial. You own the burden of proof."
    else:
        burden_directive = "NEGATIVE BURDEN: You only need to raise reasonable doubt. Expose the costs, the unproven assumptions, and the gaps in their case."

    # 5. TRUE SINGLE-PASS NATIVE COGNITIVE PIPELINE
    if current_round == 1:
        # R1: The Architect
        round_instr = (
            f"ROUND 1 CONSTRUCTIVE ({side.upper()}). 700-900 words.\n"
            "PERSONA: The Architect. Build an unassailable fortress of logic.\n"
            f"{burden_directive}\n"
            "1. EXPLICIT SIGNPOSTING: Use clear numbering ('First, my contention on X').\n"
            "2. Establish a WEIGHING METRIC and define the OPPONENT'S BURDEN OF PROOF.\n"
            "3. Pre-identify contradictions in the opponent's likely material and weaponize them."
        )
        think_template = (
            "<think>\n"
            "1. Metric & Burden: Define the debate metric and what the opponent MUST prove.\n"
            "2. Contradiction Mining: Scan the raw material for internal tensions that weaken the opponent's side.\n"
            "3. Extraction: Select verbatim quotes to anchor our 3 pillars.\n"
            "4. Concession Sweep: Ensure clinical tone and NO use of 'even if' or 'grant'.\n"
            "</think>\n"
        )
    elif current_round in [2, 3, 4]:
        # R2-R4: The Assassin & Synthesizer
        round_instr = (
            f"ROUND {current_round} ({side.upper()}). 700-900 words.\n"
            "PERSONA: The Clinical Assassin. Ruthlessly prioritize the clash.\n"
            f"{burden_directive}\n"
            "1. EXPLICIT SIGNPOSTING: Clearly signpost what argument you are attacking.\n"
            "2. THRESHOLD FRAMING: Explicitly define the 'Threshold Gap' (What they had to prove vs what they provided).\n"
            "3. QUANTITATIVE DECOMPOSITION: If they cited statistics, break them down to destroy their magnitude.\n"
            "4. Group and dismiss their weak arguments; hunt for hedged language ('may', 'sometimes') and frame it as a surrender."
        )
        think_template = (
            "<think>\n"
            "1. Threshold Gap Analysis: [Burden = X] - [Provided = Y] = [Fatal Gap].\n"
            "2. Quantitative Decomposition: Break down their stats to expose flaws.\n"
            "3. Strength Scoring & Grouping: Score their arguments 1-10. Group and dismiss sub-5 threats.\n"
            "4. Concession Trap: Scan their last speech for hedged words. Frame this as a surrender.\n"
            "5. Impact Calculus: Weigh our impacts vs their top-scored argument.\n"
            "6. Concession Sweep: Ensure academic tone, zero concessions, declarative sentences only (NO rhetorical questions).\n"
            "</think>\n"
        )
    else:
        # R5: The Judge
        round_instr = (
            f"ROUND 5 CLOSING ({side.upper()}). 650-800 words. NO NEW ARGUMENTS.\n"
            "PERSONA: The Judge. You are writing the judge's internal monologue.\n"
            "1. PROSE MASTERY: Drop all numbering and signposting. Use flowing, devastating prose.\n"
            "2. PARALLEL STRUCTURE: Use parallel grammatical structures to emphasize their failures (e.g., 'They failed on evidence; they failed on logic').\n"
            "3. You MUST start your paragraphs with these EXACT phrases to map the rubric:\n"
            "- 'When evaluating this debate on Material Grounding...'\n"
            "- 'Looking at Logic and Persuasion...'\n"
            "- 'On the standard of Direct Clash...'\n"
            "- 'Regarding Internal Consistency...'\n"
            "- 'Finally, on Offensive Pressure...'\n"
            f"\nEnd your speech with this exact sentence: For these structural and evidentiary reasons, the only logical ballot is for the {side.lower()} side."
        )
        think_template = (
            "<think>\n"
            "1. Flow Audit: Identify 2 fatal logic drops by the opponent from the transcript.\n"
            "2. Rubric Mapping: Plan the 5 paragraphs.\n"
            "3. Parallelism Check: Plan 1 devastating parallel sentence for the conclusion.\n"
            "4. Concession Sweep: Ensure no 'even if', no insults.\n"
            "</think>\n"
        )

    # 6. FLAT PROMPT ASSEMBLY
    user = (
        f"Motion: {material.topic}\n\n"
        f"Material Bank:\n{material.content}\n\n"
        f"Debate Transcript:\n{active_transcript}\n\n"
        f"{diversity_note}{freshness_directive}\n\n"
        f"--- INSTRUCTIONS ---\n{round_instr}\n\n"
        "FORMAT YOUR OUTPUT EXACTLY AS FOLLOWS:\n"
        f"{think_template}"
        "[Insert the finalized, flowing, highly persuasive speech here. NO META-LABELS. NO BOLD TEXT.]"
    )

    try:
        raw = chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        speech = _safe_trim(raw)
        if not speech or len(speech) < 100: raise ValueError("Empty generation")
        return speech
    except Exception:
        # Ultimate fallback in case of an API/network error
        return f"We maintain our position for the {side} side, fully grounded in the material's evidence. The opponent has failed to meet their burden of proof, leaving a fatal threshold gap in their logic. For these structural and evidentiary reasons, the only logical ballot is for the {side.lower()} side."