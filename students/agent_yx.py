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
        "3. MITIGATIONS/SAFEGUARDS: What specific solutions or safety valves does the material offer to address the Negative's harms? Tag them as [M1], [M2].\n"
        "4. WEIGHING METRIC: Identify the core tension (e.g., Short-term harm vs. Long-term systemic gain, Equity vs. Efficiency).\n"
        "5. THE HARDEST ATTACKS: Identify the 2 most devastating attacks against the Affirmative found in the text, AND extract the text's own counter-arguments to each. Tag them as [HARD1] and [HARD2].\n"
        "6. AFFIRMATIVE'S COUNTER-ATTACKS: Identify the 3 strongest rebuttals the Affirmative can make against the Negative's position, based on the material. Tag them as [COUNTER1], [COUNTER2], [COUNTER3]."
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
            structural_frames.append(f"Round {turn.round_index} Opener: '{fingerprint}...'")

            if len(words) > 15:
                closing = " ".join(words[-15:])
                past_closings.append(f"Round {turn.round_index} Closing: '...{closing}'")

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

    # Collect first-sentence themes from each round
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
                # Short claim fingerprint (first 5 content words)
                words = [w for w in claim.split() if len(w) > 3][:5]
                if words:
                    my_key_claims.add(" ".join(words))

        # Check if opponent's NEXT response addresses these claims
        my_round = my_t.round_index
        opp_response = [t for t in opp_turns if t.round_index == my_round + 1]
        if opp_response:
            opp_text = opp_response[0].content.lower()
            unaddressed = []
            for claim_words in my_key_claims:
                # Check if opponent mentioned any of the key claim words
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
        + "\n".join(concessions[:3])  # Cap at 3
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
        directive = "ROUND 1: OPENING. Set a measured, authoritative tone. Introduce your core case using the material. "
        if side == "affirmative":
            directive += (
                "Target 700-900 words. Build 3 full contentions grounded in [A1]-[A4] and [COUNTER1]-[COUNTER3]. "
                "Acknowledge the material's caveats, then show why your mandate overcomes them. "
                "Pre-emptively explain why alternatives (payroll taxes, value capture, parking reform) "
                "cannot substitute — briefly establish the mechanism gap. "
                "Do NOT waste time pre-empting specific negative attacks you expect — "
                "the opponent may pivot to unexpected angles, and your pre-emption will be wasted. "
                "Instead, build a case broad enough that you have material to counter any direction they take. "
                "At the end, explicitly name your 2-3 core voting issues that will persist the entire debate."
            )
        else:
            directive += (
                "ESTABLISH YOUR OWN FRAMEWORK FIRST. Open with the CONDITIONAL EFFECTIVENESS argument: the mandate "
                "assumes uniform readiness that the material does not support. Name the specific preconditions that "
                "vary across contexts. Then pivot to IMPLEMENTATION FRAGILITY. Do NOT open by reacting to the "
                "opponent's speech — set your own terms. Your first sentence must state YOUR argument. "
                "Do NOT waste time pre-empting specific affirmative attacks — "
                "the opponent may pivot to unexpected angles, and your pre-emption will be wasted. "
                "At the end, explicitly name your 2-3 core voting issues that will persist the entire debate."
            )
        return directive
    elif current_round == 5:
        return (
            "ROUND 5: CLOSING. Target 650-800 words. No new arguments. "
            "COLLAPSE the debate into 2-3 voting issues you have built across all rounds. "
            "For each voting issue: state the clash, cite evidence, explain why we win. "
            "Then do ONE paragraph of meta-weighing (certainty vs. speculation; magnitude vs. probability). "
            "End with a single, powerful ballot directive — the judge should leave with ONE sentence "
            "explaining why your side wins. Use a COMPLETELY DIFFERENT closing phrase than any previous round."
        )
    elif side == "affirmative":
        return (
            f"ROUND {current_round}: STRATEGIC CONSOLIDATION (AFFIRMATIVE).\n"
            "1. DEEPEN A CORE VOTING ISSUE (30%): Advance ONE existing voting issue deeper — "
            "add a new implication, strengthen causality, or introduce a new weighing layer. "
            "Do NOT introduce an unrelated new theme unless it directly strengthens a core voting issue.\n"
            "2. NEW COUNTER-CONSTRUCTIVE (20%): Identify ONE argument the opponent just introduced that you "
            "have not yet addressed. Build a direct, substantive response — show why it fails on its own terms "
            "using the material's evidence. Do NOT spend more than one sentence on meta-commentary.\n"
            "3. ALTERNATIVES REBUTTAL (15%): If they proposed alternatives, rebut concisely with a NEW angle.\n"
            "4. DIRECT CLASH (35%): Attack the opponent's remaining arguments. "
            "Develop each clash for 2-3 sentences. Do NOT do line-by-line rebuttal — compress and subsume."
        )
    else:
        # NEG middle rounds: simple deep-rebuttal, no cluster labels, no dropped-claim machinery
        return (
            f"ROUND {current_round} (NEGATIVE).\n"
            "- DEEP REBUTTAL: Attack their 2-3 strongest arguments directly. "
            "For each, develop your rebuttal for 3-4 sentences — show the logical gap, then explain "
            "the broader implication. Use 'Even-If' chains to show your other pillars survive even "
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

    # 7. Build Side-Specific Strategic Context
    if side == "affirmative":
        strategic_context = (
            "AFFIRMATIVE STRATEGIC GOALS:\n"
            "- Explain why delay persists (collective action problem, political cowardice)\n"
            "- Show why mandates change incentives (price signal + dedicated revenue)\n"
            "- Compare current harms vs. transitional harms — transitional harms are smaller and temporary\n"
            "- Force NEG to defend inaction: they must show that waiting is SAFER than acting\n"
            "- Weaponize any opponent concessions: show accepted premises imply your side\n"
            "AFFIRMATIVE BURDEN STRATEGY:\n"
            "- You do NOT need to prove perfect implementation everywhere.\n"
            "- You only need to prove the mandate is directionally superior to continued delay.\n"
            "- Shift the debate from 'is this perfect?' to 'is the alternative worse?'\n"
            "MANDATE = FRAMEWORK, NOT STRAITJACKET:\n"
            "- If they argue local flexibility makes the mandate an 'empty directive,' this is false. "
            "A mandate forces the ACTION (breaking political paralysis), while delegating the PARAMETERS "
            "(zone size, fee level, exemptions) to local experts. A legal requirement to price congestion "
            "gives mayors the political cover to act — something voluntary adoption never provides. "
            "Without the mandate, every mayor waits for someone else to go first."
        )
    else:
        strategic_context = (
            "NEGATIVE STRATEGIC GOALS:\n"
            "- Show that success is CONDITIONAL on preconditions that are not universal\n"
            "- Expose the sequencing fallacy: impose cost first, build conditions later\n"
            "- Use Even-If logic: grant AFF rebuttals, show your other pillars still stand\n"
            "- Weaponize any opponent concessions: show accepted premises imply their burden is unmet\n"
            "NEGATIVE BURDEN STRATEGY:\n"
            "- AFF must prove the mandate works safely across the FULL category the motion covers.\n"
            "- One major failure case is enough to reject a blanket mandate.\n"
            "- Force AFF to defend their weakest-case scenario, not just their best case.\n"
            "THREE PILLARS (rotate emphasis, evolve language each round):\n"
            "- Pillar 1: CONDITIONAL EFFECTIVENESS — mandate assumes uniform readiness ([N1]-[N3])\n"
            "- Pillar 2: IMPLEMENTATION FRAGILITY — complexity, backlash, political brittleness ([N1]-[N3])\n"
            "- Pillar 3: CAUSAL INVERSION — impose first, build trust later reverses the required sequence ([M1], [M2])"
        )

    # 8. Fetch Directives
    directive = _get_round_directive(current_round, side)

    # 9. Dynamic Prep Instructions
    if current_round == 1 and side == "affirmative":
        prep_instructions = (
            "1. Core Framework: [Plan 3 contentions with evidence tags — target 700-900 words]\n"
            "2. Alternative Pre-emption: [Why payroll taxes/value capture/parking reform cannot substitute]\n"
            "3. Current-Situation Attack: [2 ways the existing arrangement is worse]\n"
            "4. Voting Issues: [Name the 2-3 issues you will carry through all rounds]\n"
            "5. Closing Phrase: [Unique closing — avoid generic phrases]"
        )
    elif current_round == 1 and side == "negative":
        prep_instructions = (
            "1. Core Framework: [Open with CONDITIONAL EFFECTIVENESS — mandate assumes uniform readiness]\n"
            "2. Offensive Strike: [IMPLEMENTATION FRAGILITY — use your strongest negative evidence]\n"
            "3. AFF Vulnerability: [1 weakness using COUNTER1/COUNTER2 to preempt]\n"
            "4. Voting Issues: [Name the 2-3 pillars you will deepen all rounds]\n"
            "5. Closing Phrase: [Unique closing — avoid 'vote negative']"
        )
    elif current_round == 5:
        prep_instructions = (
            "1. Identify 2-3 Voting Issues: [Your strongest persistent clashes]\n"
            "2. Ballot Story: [One sentence explaining why you win — every paragraph must reinforce this]\n"
            "3. Weaponize Concessions: [Which opponent admissions seal your victory?]\n"
            "4. Meta-Weighing: [Certainty vs. speculation? Magnitude vs. probability?]\n"
            "5. Closing Phrase: [Check past closings — something COMPLETELY different]"
        )
    elif side == "affirmative":
        prep_instructions = (
            "1. Deepen a Core Issue: [Which voting issue will you advance? New angle?]\n"
            "2. New Counter: [What NEW argument did the opponent just introduce? How to defeat it?]\n"
            "3. Opponent Clusters: [Group their remaining args — which shared assumption to attack?]\n"
            "4. Closing Phrase: [Check past closings — something new]"
        )
    else:
        prep_instructions = (
            "1. Deepen a Pillar: [Which pillar to advance? New evidence or angle?]\n"
            "2. Key Rebuttal Targets: [Which 2-3 opponent arguments to attack? What's the logical gap?]\n"
            "3. Even-If Planning: [Grant their best rebuttal, show other pillars survive]\n"
            "4. Closing Phrase: [Check past closings — something new]"
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
        "2. NO FABRICATION — You may ONLY cite facts, statistics, city names, or studies that are "
        "EXPLICITLY in the Material Evidence Bank. If the material does not name a specific city or "
        "statistic, you MUST NOT invent one. Argue from principles and mechanisms instead.\n\n"
        "3. STRATEGIC COHERENCE — Maintain 2-3 persistent voting issues across all rounds. Deepen them "
        "rather than rotating themes. Every new argument must strengthen a core voting issue. "
        "A judge who hears 10 speeches will remember coherent narratives, not scattered subpoints.\n\n"
        "4. DIRECT CLASH — Attack the opponent's arguments directly and deeply. "
        "Do NOT do line-by-line rebuttal. Compress and subsume weaker arguments into larger thematic clashes. "
        "If they claim you 'dropped' something, check the transcript and answer in one sentence.\n\n"
        "5. NO EMPTY REPETITION — Evolve your language every round. Check your past arguments and "
        "structural frames below to avoid overlap. Use a different opener and closing every round.\n\n"
        "6. MEASURED TONE — Conversational and persuasive. No aggressive jargon ('destroyed', 'fallacy', "
        "'strawman'). No bold text, no bullet points, no markdown headers in the speech.\n\n"
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
        "specific statistics, or specific study outcomes unless EXPLICITLY quoted in the "
        "Material Evidence Bank above. If unsure, do NOT include it. Argue from principles.\n\n"
        "=== REMINDER: NEVER DISPUTE OPPONENT'S EVIDENCE ===\n"
        "You have a condensed extraction of the material. The opponent has the full text. "
        "NEVER say their quote 'does not appear' or 'is not in the material' — it probably is, "
        "just in a section your extraction did not include. Attack their ARGUMENT, not their source."
    )

    # Build user prompt
    sections = [
        f"Motion: {material.topic}\n\n"
        f"Material Evidence Bank:\n{material_map}\n\n"
        f"{fabrication_reminder}",
        f"Transcript (Last {MAX_TURNS} turns):\n{transcript}\n\n",
        f"--- YOUR PAST ARGUMENTS (DO NOT REPEAT THESE POINTS) ---\n"
        f"{past_arguments}\n\n",
        f"--- YOUR PAST STRUCTURAL FRAMES (VARY YOUR OPENERS) ---\n"
        f"{structural_frames}\n\n",
        f"--- YOUR PAST CLOSINGS (USE A DIFFERENT CLOSING EVERY ROUND) ---\n"
        f"{past_closings}\n\n",
        f"--- OPPONENT'S KEY ARGUMENTS (CLASH THESE DIRECTLY) ---\n"
        f"{opponent_key_args}\n\n",
    ]

    # Only add these for rounds after R1 (they need history)
    # AFF: inject R2+ (strategic coherence helps AFF)
    # NEG: inject R5 only (meta-framework hurts NEG in middle rounds)
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
            f"We firmly maintain our stance for the {side} side, grounded entirely in the material's evidence. "
            "The opposition has not met their burden of proof on the central clashes we have identified."
        )
