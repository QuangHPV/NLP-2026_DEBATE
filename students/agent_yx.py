import re
import hashlib
from debate_eval.api import chat

# Global cache to compute the material map exactly once (Saves Memory & Time)
_MATERIAL_CACHE = {}


def _get_material_map(material):
    """Extracts a structured evidence bank with explicit tags, including the hardest attacks."""
    key = hashlib.md5((material.topic + material.content).encode('utf-8')).hexdigest()
    if key in _MATERIAL_CACHE:
        return _MATERIAL_CACHE[key]

    sys_prompt = (
        "You are an expert debate analyst. Extract a structured evidence bank from the material. "
        "Output ONLY the tagged evidence below. No introductory or concluding remarks. No filler text. Use exact quotes."
    )
    user_prompt = (
        f"Motion: {material.topic}\n\n"
        f"Material:\n{material.content}\n\n"
        "Extract the following as tagged evidence. No filler text:\n"
        "1. AFFIRMATIVE AMMO: Extract the 4 strongest factual quotes supporting the motion. Tag them as [A1], [A2], [A3], [A4].\n"
        "2. NEGATIVE AMMO: Extract the 3 strongest factual quotes opposing the motion. Tag them as [N1], [N2], [N3].\n"
        "3. MITIGATIONS/SAFEGUARDS: What specific solutions or safety valves does the material offer to address the Negative\'s harms? Tag them as [M1], [M2].\n"
        "4. WEIGHING METRIC: Identify the core tension (e.g., Short-term harm vs. Long-term systemic gain, Equity vs. Efficiency).\n"
        "5. THE HARDEST ATTACKS: Identify the 2 most devastating attacks against the Affirmative found in the text, AND extract the text\'s own counter-arguments to each. Tag them as [HARD1] and [HARD2].\n"
        "6. AFFIRMATIVE\'S COUNTER-ATTACKS: Identify the 3 strongest rebuttals the Affirmative can make against the Negative\'s position, based on the material. Tag them as [COUNTER1], [COUNTER2], [COUNTER3]."
    )

    try:
        resp = chat([{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}])
        _MATERIAL_CACHE[key] = resp
        return resp
    except Exception:
        return material.content


def _get_past_arguments(history, side):
    """Extracts paragraph-level topic map, structural fingerprint, and closing fingerprint."""
    past_args = []
    structural_frames = []
    past_closings = []

    for turn in history:
        if turn.side.lower() == side.lower():
            paragraphs = [p.strip() for p in re.split(r'\n+', turn.content.strip()) if p.strip()]
            topic_map = []
            for p in paragraphs[:6]:
                sentences = re.split(r'(?<=[.!?])\s+', p)
                if sentences:
                    core_claim = " ".join(sentences[:2]).strip()
                    if len(core_claim) > 160:
                        core_claim = core_claim[:157] + "..."
                    topic_map.append(core_claim)

            summary = " | ".join(topic_map)
            past_args.append(f"Round {turn.round_index} Topics: {summary}")

            words = turn.content.strip().split()
            fingerprint = " ".join(words[:12])
            structural_frames.append(f"Round {turn.round_index} Opener: \'{fingerprint}\'...'")

            if len(words) > 15:
                closing = " ".join(words[-15:])
                past_closings.append(f"Round {turn.round_index} Closing: \'...{closing}\''")

    arg_str = "\n".join(past_args) if past_args else "No previous arguments."
    frame_str = "\n".join(structural_frames) if structural_frames else "No previous frames."
    close_str = "\n".join(past_closings) if past_closings else "No previous closings."

    return arg_str, frame_str, close_str


def _get_opponent_key_args(history, my_side):
    """Extract key claims from the opponent's most recent speech for targeted clash."""
    if not history:
        return "No opponent speech yet — this is the opening."

    opp_side = "negative" if my_side.lower() == "affirmative" else "affirmative"
    opp_turns = [t for t in history if t.side.lower() == opp_side]

    if not opp_turns:
        return "No opponent speech yet — this is the opening."

    last_opp = opp_turns[-1]
    paragraphs = [p.strip() for p in re.split(r'\n+', last_opp.content.strip()) if p.strip()]

    key_args = []
    for p in paragraphs[:5]:
        sentences = re.split(r'(?<=[.!?])\s+', p)
        if sentences:
            claim = " ".join(sentences[:2]).strip()
            if len(claim) > 200:
                claim = claim[:197] + "..."
            key_args.append(claim)

    if not key_args:
        return "Could not parse opponent's arguments."

    return (
        f"Round {last_opp.round_index} Opponent ({opp_side.upper()}) Key Claims:\n"
        + "\n".join(f"- {a}" for a in key_args)
    )


def _get_core_voting_issues(history, side):
    """Extract persistent voting themes from prior speeches to maintain strategic coherence."""
    if not history:
        return ""

    my_turns = [t for t in history if t.side.lower() == side.lower()]
    if not my_turns:
        return ""

    themes_by_round = []
    for t in my_turns:
        paragraphs = [p.strip() for p in re.split(r'\n+', t.content.strip()) if p.strip()]
        round_themes = []
        for p in paragraphs[:3]:
            sentences = re.split(r'(?<=[.!?])\s+', p)
            if sentences:
                claim = sentences[0].strip()
                if len(claim) > 100:
                    claim = claim[:97] + "..."
                round_themes.append(claim)
        if round_themes:
            themes_by_round.append(f"R{t.round_index}: {'; '.join(round_themes)}")

    if not themes_by_round:
        return ""

    return (
        "--- YOUR CORE VOTING ISSUES (from your past speeches) ---\n"
        "Identify the 2-3 themes that appeared across MULTIPLE rounds. These are your "
        "voting issues. Every new argument you make MUST strengthen one of these — "
        "do NOT introduce unrelated themes.\n"
        + "\n".join(themes_by_round)
    )


def _get_concessions(history, my_side):
    """Extract points the opponent effectively conceded or failed to address."""
    if len(history) < 2:
        return ""

    opp_side = "negative" if my_side.lower() == "affirmative" else "affirmative"
    my_turns = [t for t in history if t.side.lower() == my_side.lower()]
    opp_turns = [t for t in history if t.side.lower() == opp_side]

    if len(my_turns) < 1 or len(opp_turns) < 1:
        return ""

    concessions = []
    for my_t in my_turns:
        my_content_lower = my_t.content.lower()
        my_key_claims = set()
        paras = [p.strip() for p in re.split(r'\n+', my_t.content.strip()) if p.strip()]
        for p in paras[:4]:
            sentences = re.split(r'(?<=[.!?])\s+', p)
            if sentences:
                claim = sentences[0].strip().lower()
                words = [w for w in claim.split() if len(w) > 3][:5]
                if words:
                    my_key_claims.add(" ".join(words))

        my_round = my_t.round_index
        opp_response = [t for t in opp_turns if t.round_index == my_round + 1]
        if opp_response:
            opp_text = opp_response[0].content.lower()
            unaddressed = []
            for claim_words in my_key_claims:
                claim_words_present = sum(1 for w in claim_words.split() if w in opp_text)
                if claim_words_present <= 1:
                    unaddressed.append(claim_words)
            if unaddressed:
                concessions.append(
                    f"R{my_round}: You argued about [{'; '.join(unaddressed[:2])}] "
                    f"— opponent may not have directly answered this."
                )

    if not concessions:
        return ""

    return (
        "--- OPPONENT CONCESSIONS (weaponize these) ---\n"
        "The following points from your past speeches were not directly answered. "
        "Explain why these accepted premises logically imply your side wins:\n"
        + "\n".join(concessions[:3])
    )


def _safe_trim(text, max_chars=6800):
    """Guarantees the speech is never truncated mid-sentence by the engine."""
    text = str(text or "").strip()
    match = re.search(r"<speech>\s*(.*?)\s*(?:</speech>|$)", text, flags=re.DOTALL | re.IGNORECASE)
    speech = match.group(1) if match else text

    speech = re.sub(r"(?is)<prep>.*?</prep>", "", speech)
    speech = re.sub(r"(?im)^\s*(affirmative|negative) closing statement.*$", "", speech)
    speech = re.sub(r"(?i)^(Here is the speech:|Speech:)\s*", "", speech)
    speech = speech.replace("**", "")
    speech = re.sub(r"\n{3,}", "\n\n", speech).strip()

    if len(speech) <= max_chars:
        return speech

    trimmed = speech[:max_chars].rstrip()
    paragraph_cut = trimmed.rfind("\n\n")
    sentence_cut = max(trimmed.rfind(". "), trimmed.rfind("! "), trimmed.rfind("? "))

    if paragraph_cut > max_chars * 0.7:
        return trimmed[:paragraph_cut].rstrip()
    elif sentence_cut > max_chars * 0.7:
        return trimmed[:sentence_cut + 1].rstrip()

    return trimmed


def _get_round_directive(current_round, side):
    """Positive framing directives. AFF uses strategic coherence; NEG uses direct deep-rebuttal."""
    if current_round == 1:
        directive = "ROUND 1: OPENING. Target 700-900 words. Set a measured, authoritative tone. "
        if side == "affirmative":
            directive += (
                "Introduce your core case using the material. Build 3 full contentions grounded in [A1]-[A4] and [COUNTER1]-[COUNTER3]. "
                "Acknowledge the material\'s caveats, then show why your mandate overcomes them. "
                "Briefly identify the main status quo alternatives the material mentions and explain why each cannot substitute for the mandate. "
                "Do NOT waste time pre-empting specific negative attacks you expect. "
                "At the end, explicitly name your 2-3 core voting issues that will persist the entire debate."
            )
        else:
            directive += (
                "ESTABLISH YOUR OWN FRAMEWORK FIRST. Open with the CONDITIONAL EFFECTIVENESS argument: the mandate "
                "assumes uniform readiness that the material does not support. Name the specific preconditions that "
                "vary across contexts. Then pivot to IMPLEMENTATION FRAGILITY. Do NOT open by reacting to the "
                "opponent\'s speech — set your own terms. Your first sentence must state YOUR argument. "
                "Do NOT waste time pre-empting specific affirmative attacks. "
                "At the end, explicitly name your 2-3 core voting issues that will persist the entire debate."
            )
        return directive
    elif current_round == 5:
        return (
            "ROUND 5: CLOSING. Target 650-800 words. No new arguments. "
            "COLLAPSE the debate into 2-3 voting issues you have built across all rounds. "
            "For each voting issue: state the clash, cite evidence, explain why we win. "
            "Then weigh the worlds on Magnitude, Probability, and Reversibility — reference the judge\'s evaluation criteria (material grounding, logical reasoning, direct clash, internal consistency, offensive pressure) to frame why we prevail on each. "
            "End with a single, powerful ballot directive — the judge should leave with ONE sentence "
            "explaining why your side wins. Use a COMPLETELY DIFFERENT closing phrase than any previous round."
        )
    elif side == "affirmative":
        if current_round == 4:
            return (
                "ROUND 4: PRE-CLOSING CRYSTALLIZATION (AFFIRMATIVE). Target 700-900 words.\n"
                "1. COLLAPSE the debate into 2-3 voting issues. For each clash: state it, cite evidence, explain why you are winning.\n"
                "2. COUNTER any opponent argument that still needs answer — one paragraph max.\n"
                "3. Do ONE paragraph of impact weighing: compare your strongest voting issue against theirs "
                "on magnitude, probability, and reversibility.\n"
                "4. End by framing the choice the judge faces — set up your closing."
            )
        else:
            return (
                f"ROUND {current_round}: STRATEGIC CONSOLIDATION (AFFIRMATIVE). Target 700-900 words.\n"
                "1. DEEPEN a core voting issue — add a new implication, strengthen causality, or introduce a new weighing dimension.\n"
                "2. COUNTER the strongest new argument the opponent just introduced — show why it fails on its own terms.\n"
                "3. ADVANCE one NEW constructive argument from your Evidence Bank — a fresh evidence tag ([A1]-[A4], [COUNTER1]-[COUNTER3], "
                "[M1]-[M2]), implication, or angle you have not yet deployed. Every round must add something new to the table.\n"
                "4. CLASH on the opponent\'s remaining arguments — compress and subsume into larger thematic clashes. "
                "Do NOT do line-by-line rebuttal."
            )
    else:
        return (
            f"ROUND {current_round} (NEGATIVE). Target 700-900 words.\n"
            "- DEEP REBUTTAL: Attack their 2-3 strongest arguments directly. "
            "For each, develop your rebuttal for 3-4 sentences — show the logical gap, then explain "
            "the broader implication. Use \'Even-If\' chains to show your other pillars survive even "
            "their best point.\n"
            "- ADVANCE YOUR PILLARS: Add new evidence, angle, or causal link to strengthen "
            "ONE of your three pillars.\n"
            "- BURDEN PRESSURE: One sentence reminding the judge what AFF must prove "
            "and where they fall short."
        )


def speak(material, history, side):
    current_round = (len(history) // 2) + 1

    # 1. Fetch Material Map (cached after first extraction)
    material_map = _get_material_map(material)

    # 2. Extract Previous Arguments Summary, Structural Frames, and Closing Fingerprints
    past_arguments, structural_frames, past_closings = _get_past_arguments(history, side)

    # 3. Extract Opponent's Key Arguments from their last speech
    opponent_key_args = _get_opponent_key_args(history, side)

    # 4. Extract Core Voting Issues (strategic coherence)
    core_voting_issues = _get_core_voting_issues(history, side)

    # 5. Extract Concessions (weaponization)
    concessions = _get_concessions(history, side)

    # 6. Format Transcript
    MAX_TURNS = 8
    recent_history = history[-MAX_TURNS:] if len(history) > MAX_TURNS else history
    transcript = "\n\n".join(
        f"Round {t.round_index} | {t.side.upper()}:\n{t.content}" for t in recent_history
    )
    if not transcript:
        transcript = "No previous turns yet. This is the opening speech."

    # 7. Build Side-Specific Strategic Context (DOMAIN-NEUTRAL)
    if side == "affirmative":
        strategic_context = (
            "AFFIRMATIVE STRATEGIC GOALS:\n"
            "- Establish why inaction persists (collective action problem, political barriers, or status quo bias)\n"
            "- Show how the mandate creates a mechanism for change that the status quo lacks\n"
            "- Compare status quo harms vs. transitional harms — show transitional harms are smaller and temporary\n"
            "- Force NEG to defend the current state: they must prove waiting is SAFER than acting\n"
            "AFFIRMATIVE BURDEN STRATEGY:\n"
            "- You do NOT need to prove perfect implementation everywhere.\n"
            "- You only need to prove the mandate is directionally superior to continued inaction.\n"
            "- Shift the debate from \'is this perfect?\' to \'is the alternative worse?\'\n"
            "- REVERSIBILITY FLIP: If opponent argues reversibility or opportunity cost, flip it: "
            "the status quo is actively accumulating irreversible harms every day of delay. "
            "The mandate\'s transitional costs are temporary and reversible; the status quo\'s "
            "harms compound and become permanent.\n"
            "- If opponent demands exact numbers or percentages to prove net benefit, refuse the framing: policy debate requires proving a structural mechanism, not delivering statistical prophecy. Show your mechanism directionally eliminates a systemic harm while costs are bounded and reversible."
        )
    else:
        strategic_context = (
            "NEGATIVE STRATEGIC GOALS:\n"
            "- Show that success is CONDITIONAL on preconditions that are not universal\n"
            "- Expose the sequencing problem: the mandate imposes costs before readiness is achieved\n"
            "- Use Even-If logic: grant AFF rebuttals, show your other pillars still stand\n"
            "- REVERSIBILITY FLIP: If opponent argues long-term benefits outweigh short-term costs, "
            "flip it: the mandate causes irreversible structural lock-in of capital, political will, "
            "and institutional disruption. Slow, reversible alternatives preserve optionality.\n"
            "- If opponent demands exact numbers to prove the mandate causes net harm, flip it: they bear the burden of proof for a blanket mandate. Demand they quantify the probability of success across the full scope of the motion — which the material shows they cannot.\n"
            "NEGATIVE BURDEN STRATEGY:\n"
            "- AFF must prove the mandate works safely across the FULL scope the motion covers.\n"
            "- One major failure case is enough to reject a blanket mandate.\n"
            "- Force AFF to defend their weakest-case scenario, not just their best case.\n"
            "THREE PILLARS (rotate emphasis, evolve language each round):\n"
            "- Pillar 1: CONDITIONAL EFFECTIVENESS — mandate assumes uniform readiness ([N1]-[N3])\n"
            "- Pillar 2: IMPLEMENTATION FRAGILITY — complexity, backlash, and unintended consequences ([N1]-[N3])\n"
            "- Pillar 3: CAUSAL INVERSION — costs imposed before enabling conditions are met ([M1], [M2])"
        )

    # 8. Fetch Directives
    directive = _get_round_directive(current_round, side)

    # 9. Dynamic Prep Instructions
    if current_round == 1 and side == "affirmative":
        prep_instructions = (
            "1. Core Framework: [Plan 3 contentions with evidence tags]\n"
            "2. Alternative Gap: [Why status quo alternatives cannot substitute for the mandate]\n"
            "3. Current-Situation Attack: [2 ways the existing arrangement is worse]\n"
            "4. Voting Issues: [Name the 2-3 issues you will carry through all rounds]\n"
            "5. Opening Hook: [A specific, concrete image or scenario — NOT \'Ladies and gentlemen\']\n"
            "6. Closing Phrase: [Unique closing — avoid generic phrases]"
        )
    elif current_round == 1 and side == "negative":
        prep_instructions = (
            "1. Core Framework: [Open with CONDITIONAL EFFECTIVENESS — mandate assumes uniform readiness]\n"
            "2. Offensive Strike: [IMPLEMENTATION FRAGILITY — use your strongest negative evidence]\n"
            "3. AFF Vulnerability: [1 weakness using COUNTER1/COUNTER2]\n"
            "4. Voting Issues: [Name the 2-3 pillars you will deepen all rounds]\n"
            "5. Opening Hook: [A specific, concrete scenario — NOT \'Ladies and gentlemen\']\n"
            "6. Closing Phrase: [Unique closing]"
        )
    elif current_round == 5:
        prep_instructions = (
            "1. Identify 2-3 Voting Issues: [Your strongest persistent clashes]\n"
            "2. Ballot Story: [One sentence explaining why you win]\n"
            "3. Weaponize Concessions: [Which opponent admissions seal your victory?]\n"
            "4. Meta-Weighing: [Certainty vs. speculation? Magnitude vs. probability?]\n"
            "5. Closing Phrase: [Check past closings — something COMPLETELY different]"
        )
    elif side == "affirmative":
        if current_round == 4:
            prep_instructions = (
                "1. Voting Issues So Far: [Which 2-3 clashes have you won?]\n"
                "2. Impact Weighing: [Magnitude / Probability / Reversibility — who wins overall?]\n"
                "3. Counter Remaining: [What opponent argument still needs answer?]\n"
                "4. Opening Hook: [New structure — check past openers and DIFFER]\n"
                "5. Closing Phrase: [Save your absolute best for R5]"
            )
        else:
            prep_instructions = (
                "1. Deepen a Core Issue: [Which voting issue? New angle?]\n"
                "2. Counter New Argument: [What did the opponent introduce?]\n"
                "3. New Constructive: [Fresh evidence tag or angle from your Evidence Bank — [A1]-[A4], [COUNTER1]-[COUNTER3], [M1]-[M2]?]\n"
                "4. Clash Targets: [Which opponent arguments to subsume into larger themes?]\n"
                "5. Opening Hook: [A new rhetorical structure — check past openers and DIFFER]\n"
                "6. Closing Phrase: [Check past closings — something new]"
            )
    else:
        prep_instructions = (
            "1. Deepen a Pillar: [Which pillar? New evidence or angle?]\n"
            "2. Key Rebuttal Targets: [Which 2-3 opponent arguments? What\'s the logical gap?]\n"
            "3. Even-If Planning: [Grant their best rebuttal, show other pillars survive]\n"
            "4. Opening Hook: [A new rhetorical structure — check past openers and DIFFER]\n"
            "5. Closing Phrase: [Check past closings — something new]"
        )

    target_length = (
        "650-800 words of concentrated crystallization."
        if current_round == 5
        else "700-900 words of flowing, persuasive prose."
    )

    # 10. The System Prompt
    system = (
        "You are an expert debate speaker evaluated by an AI judge on five criteria: "
        "grounding in material, logical reasoning, direct clash, no empty repetition, and offensive pressure.\n\n"
        "CORE RULES:\n\n"
        "1. STRICT GROUNDING — You are working from a CONDENSED Evidence Bank (selected quotes), "
        "while the opponent has access to the full unabridged text. NEVER accuse the opponent of "
        "fabricating, misquoting, or inventing evidence. Assume their textual citations are 100% "
        "accurate. If you do not recognize a quote, assume it is from a part of the material your "
        "extraction did not cover. Attack the LOGIC, CONTEXT, and IMPACT of their evidence — never "
        "its provenance. Your own citations must come from YOUR Evidence Bank tags.\n\n"
        "2. NO FABRICATION — You may ONLY cite facts, statistics, or studies that are "
        "EXPLICITLY in your Material Evidence Bank. NEVER name a real-world city, country, or "
        "organization (London, Stockholm, New York, Singapore, etc.) unless that name appears "
        "EXPLICITLY in your Evidence Bank tags. When the opponent mentions cities or data you do "
        "not recognize, do NOT repeat or reference them — pivot to principles and mechanisms.\n\n"
        "3. STRATEGIC COHERENCE — Maintain 2-3 persistent voting issues across all rounds. Deepen them "
        "rather than rotating themes. Every new argument must strengthen a core voting issue.\n\n"
        "4. DIRECT CLASH — Attack the opponent\'s arguments directly and deeply. "
        "Do NOT do line-by-line rebuttal. Compress and subsume weaker arguments into larger thematic clashes. "
        "If they claim you \'dropped\' or \'conceded\' something, briefly state which round you addressed it and move on — never let a false drop accusation stand uncontested.\n\n"
        "5. NO EMPTY REPETITION — Evolve your language every round. Check your past arguments and "
        "structural frames below to avoid overlap. Your opening sentence MUST use a different "
        "structure and salutation every round — never begin two speeches the same way.\n\n"
        "6. MEASURED TONE — Conversational and persuasive. No bold text, no bullet points, no "
        "markdown headers in the speech. BANNED meta-phrases: \'obvious fallacy\', \'textbook case of\', "
        "\'masterclass in\', \'desperate attempt\', \'house of cards\'. Instead of labeling the "
        "opponent\'s argument, DEMONSTRATE why it fails through evidence and logic.\n\n"
        "7. NO CONCESSION WITHOUT LOOP-CLOSE — NEVER say 'I do not deny', 'I concede', 'I admit', "
        "or 'That is true' about an opponent's argument without IMMEDIATELY closing the loop: "
        "state why the status quo produces a WORSE version of that exact same harm, or why the "
        "opponent's alternative creates a larger version of the problem they highlighted. "
        "Every concession must be followed by a counter-attack in the same sentence.\n\n"
        "OUTPUT FORMAT:\n"
        "<prep>\n"
        f"{prep_instructions}\n"
        "</prep>\n"
        "<speech>\n"
        f"Your final spoken words. Target: {target_length}\n"
        "</speech>"
    )

    # Build fabrication reminder — covers ALL rounds
    fabrication_reminder = (
        "\n\n=== REMINDER: NO FABRICATION ===\n"
        "Do NOT name specific cities (London, Stockholm, Singapore, Milan, New York, etc.), "
        "specific statistics, or specific study outcomes unless EXPLICITLY quoted in your "
        "Evidence Bank above. When the opponent mentions a city or statistic you don\'t recognize, "
        "do NOT repeat or reference it. Argue from principles and mechanisms.\n\n"
        "=== REMINDER: NEVER DISPUTE OPPONENT\'S EVIDENCE ===\n"
        "You have a condensed extraction. The opponent has the full text. "
        "NEVER say their quote \'does not appear\' or \'is not in the material\' — it probably is. "
        "Attack their ARGUMENT, not their source."
    )

    # Build user prompt
    sections = [
        f"Motion: {material.topic}\n\n"
        f"Material Evidence Bank:\n{material_map}\n\n"
        f"{fabrication_reminder}",
        f"Transcript (Last {MAX_TURNS} turns):\n{transcript}\n\n",
        f"--- YOUR PAST ARGUMENTS (DO NOT REPEAT THESE POINTS) ---\n"
        f"{past_arguments}\n\n",
        f"--- YOUR PAST STRUCTURAL FRAMES (USE A DIFFERENT OPENER EVERY ROUND) ---\n"
        f"{structural_frames}\n\n",
        f"--- YOUR PAST CLOSINGS (USE A DIFFERENT CLOSING EVERY ROUND) ---\n"
        f"{past_closings}\n\n",
        f"--- OPPONENT\'S KEY ARGUMENTS (CLASH THESE DIRECTLY) ---\n"
        f"{opponent_key_args}\n\n",
    ]

    # Only add these for rounds after R1
    if current_round > 1:
        if side == "affirmative":
            if core_voting_issues:
                sections.append(f"{core_voting_issues}\n\n")
            if concessions:
                sections.append(f"{concessions}\n\n")
        elif current_round == 5:
            if core_voting_issues:
                sections.append(f"{core_voting_issues}\n\n")
            if concessions:
                sections.append(f"{concessions}\n\n")

    sections.append(
        f"Side: {side.upper()}\n"
        f"{strategic_context}\n\n"
        f"Directive: {directive}\n\n"
        "Execute your <prep> block, then deliver your <speech>."
    )

    user = "".join(sections)

    try:
        raw_output = chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )

        trim_limit = 6800
        final_speech = _safe_trim(raw_output, max_chars=trim_limit)

        if not final_speech or len(final_speech) < 100:
            raise ValueError("Empty generation")

        return final_speech

    except Exception:
        return (
            f"We firmly maintain our stance for the {side} side, grounded entirely in the material\'s evidence. "
            "The opposition has not met their burden of proof on the central clashes we have identified."
        )
