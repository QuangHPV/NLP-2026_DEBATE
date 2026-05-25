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
        "You are an expert debate analyst. Extract a structured, highly strategic evidence bank from the material. "
        "Be precise and concise. Use exact quotes wherever possible."
    )
    user_prompt = (
        f"Motion: {material.topic}\n\n"
        f"Material:\n{material.content}\n\n"
        "Extract the following into a concise battle plan:\n"
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


def _get_toolkit(side):
    """Provides domain-neutral, contextual tools for any topic."""
    if side == "affirmative":
        return (
            "AFFIRMATIVE TOOLKIT:\n"
            "- The Alternative Kill: If they propose a softer alternative (e.g., voluntary measures, alternative funding, "
            "incremental steps), expose the mechanism gap: explicitly state why their alternative lacks the unique structural "
            "mechanism required to actually solve the root cause. Without our mandate, the core problem remains untouched.\n"
            "- The Mechanism Argument: If they propose payroll taxes, value capture, parking reform, or car-free days, "
            "explain that each of those addresses only ONE dimension of the problem (revenue, OR pricing, OR behavior) "
            "while our mandate addresses ALL THREE simultaneously: it prices the externality, generates dedicated revenue, "
            "AND shifts behavior at the point of decision. IMPORTANT: Do NOT always call this a 'triple mechanism' — "
            "describe the same concept using DIFFERENT LANGUAGE each round to avoid sounding repetitive.\n"
            "- The Catch-22: If they argue 'wait until conditions are ready' or 'build capacity first', point out that "
            "the mandate is exactly what forces the system to adapt and generates the resources/political will to build "
            "those conditions. Delay guarantees paralysis.\n"
            "- Mitigations: Acknowledge valid transition or equity concerns reasonably, then instantly neutralize them "
            "using your extracted Mitigations [M1]/[M2]. Then pivot: even with the concern, the current situation is worse.\n"
            "- Escalate Pressure: Each round, press harder on the hidden costs of doing nothing. Frame their defense as "
            "defending a system that already harms the people they claim to protect.\n"
            "- Anti-Fabrication Defense: If the opponent cites specific city names, study outcomes, or statistics that "
            "are not in the material, you can point out that those claims go beyond the provided evidence. However, do "
            "not make this a major argument — one brief mention is enough."
        )
    else:
        return (
            "NEGATIVE TOOLKIT — THREE STRUCTURAL PILLARS:\n\n"
            "Pillar 1 — CONDITIONAL EFFECTIVENESS: The material shows that the policy's success depends on specific "
            "preconditions (infrastructure, capacity, governance, public readiness). A blanket mandate forces adoption "
            "even where these preconditions may not exist. The AFF bears the burden of proving the mandate works safely "
            "across EVERY context the motion covers. Reference [N3] or any [HARD] tag about local variation or "
            "implementation challenges.\n\n"
            "Pillar 2 — IMPLEMENTATION FRAGILITY: The material warns about complexity, coordination challenges, or "
            "political resistance. A mandate imposed before adequate preparation risks backlash, non-compliance, or "
            "outcomes worse than the current situation. This is not a design flaw the AFF can fix — it is a structural risk "
            "inherent in compulsion. Reference [HARD1] or [HARD2].\n\n"
            "Pillar 3 — CAUSAL INVERSION: The material suggests that acceptance and success require trust, capacity, "
            "or readiness that builds over time. The mandate's sequence — impose first, build conditions later — may "
            "invert the required causal chain. The AFF promises future relief, but the material's mitigations [M1]/[M2] "
            "themselves may depend on preconditions that do not yet exist. Reference [M1] or [M2] to show mitigations "
            "are precondition-dependent.\n\n"
            "HOW TO USE THESE PILLARS:\n"
            "- Rotate emphasis across rounds: lead with Pillar 1 in R1-R2, deepen Pillar 2 in R3, crystallize with "
            "Pillar 3 in R4-R5. Do not repeat the same pillar framing verbatim — evolve it.\n"
            "- When the AFF attacks one pillar, use 'Even-If' logic: grant their rebuttal, then show the OTHER pillars "
            "still stand. A mandate must survive ALL pillars, not just one.\n"
            "- When the AFF presents new evidence, ask: does this solve ALL THREE pillars, or just one?\n\n"
            "BANNED ARGUMENT: Do NOT propose a vague alternative (e.g., 'better funding,' 'voluntary measures,' "
            "'incremental steps') that the material itself undermines. If the material says existing mechanisms are "
            "insufficient, the AFF will use it to destroy your alternative. Instead, argue that the AFF's burden is "
            "to prove the mandate is uniquely necessary AND works everywhere — and that local, sequenced choice is "
            "safer than a one-size-fits-all mandate."
        )


def _get_round_directive(current_round, side):
    """Positive framing directives focusing on dynamic clash."""
    if current_round == 1:
        directive = "ROUND 1: OPENING. Set a measured, authoritative tone. Introduce your core case using the material. "
        if side == "affirmative":
            directive += (
                "Target 800-950 words. Build 3 full contentions grounded in [A1]-[A4] and [COUNTER1]-[COUNTER3]. "
                "Proactively address the [HARD1] and [HARD2] attacks naturally before the opponent can use them. "
                "Acknowledge the material's caveats, then show why your mandate overcomes them. "
                "Crucially: ALSO pre-emptively explain why alternatives (payroll taxes, value capture, parking reform) "
                "cannot substitute for our mandate — briefly establish the mechanism gap in your opening. "
                "End with forward momentum. Do NOT use the phrase 'triple mechanism' — describe the concept in "
                "your own words."
            )
        else:
            directive += (
                "ESTABLISH YOUR OWN FRAMEWORK FIRST. Open with the CONDITIONAL EFFECTIVENESS argument: the mandate "
                "assumes uniform readiness that the material does not support. Name the specific preconditions that "
                "vary across contexts. Then pivot to IMPLEMENTATION FRAGILITY. Do NOT open by accepting the AFF's "
                "framing and arguing defensively within it — set your own terms."
            )
        return directive
    elif current_round == 5:
        return (
            "ROUND 5: CLOSING. Target 650-800 words. Do not introduce new arguments. "
            "Structure: (1) Name the 2-3 most critical voting issues. "
            "(2) For each: state the clash, cite evidence, explain why we win — develop each for 3-4 sentences. "
            "(3) One paragraph of meta-weighing (certainty of harm vs. speculation of benefit; magnitude vs. probability). "
            "(4) End with a single, powerful ballot directive. Use a COMPLETELY DIFFERENT closing phrase than any previous round."
        )
    elif side == "affirmative":
        return (
            f"ROUND {current_round}: MIDDLE GAME (AFFIRMATIVE). Structure your speech in this order:\n"
            "1. NEW CONSTRUCTIVE (35%): Introduce ONE genuinely NEW angle or piece of evidence the opponent has not "
            "addressed. This must be a fresh expansion of your case, not a rehash of a previous round's theme. "
            "Use a different framing device each round — e.g., one round use an economic lens, another use a public "
            "health angle, another use an equity justice frame. Use [A1]-[A4], [COUNTER1]-[COUNTER3], or new angles "
            "from the material.\n"
            "2. DROPPED-CLAIM CHECK (5%): If the opponent claimed you 'dropped' an argument, ONE sentence is enough "
            "to say you addressed it and where. Do NOT spend more than one sentence on this.\n"
            "3. ALTERNATIVES REBUTTAL (15%): If the opponent proposed alternatives (payroll taxes, value capture, "
            "parking reform, car-free days, HOV lanes, land-value tax, etc.), rebut them concisely. Do NOT repeat "
            "the same rebuttal language from a previous round — find a new angle each time.\n"
            "4. DIRECT CLASH (45%): Name their specific arguments from their last speech and answer them directly. "
            "Use 'Even-If' subsumption. Develop each clash for 2-3 sentences before moving on."
        )
    else:
        return (
            f"ROUND {current_round}: MIDDLE GAME (NEGATIVE). Dedicate 80% to DIRECT CLASH. "
            "Name their specific arguments from the transcript and dismantle them. "
            "Use 'Even-If' logic from your Toolkit. "
            "Develop each clash point for at least 3 sentences before moving on — shallow rebuttals lose to deep ones. "
            "Advance to the next structural pillar if you have exhausted the current one. "
            "Do NOT repeat your earlier-round framing word-for-word — evolve it with new evidence or new angles."
        )


def speak(material, history, side):
    current_round = (len(history) // 2) + 1

    # 1. Fetch Material Map (cached after first extraction)
    material_map = _get_material_map(material)

    # 2. Extract Previous Arguments Summary, Structural Frames, and Closing Fingerprints
    past_arguments, structural_frames, past_closings = _get_past_arguments(history, side)

    # 3. Extract Opponent's Key Arguments from their last speech
    opponent_key_args = _get_opponent_key_args(history, side)

    # 4. Format Transcript
    MAX_TURNS = 8
    recent_history = history[-MAX_TURNS:] if len(history) > MAX_TURNS else history
    transcript = "\n\n".join(
        f"Round {t.round_index} | {t.side.upper()}:\n{t.content}" for t in recent_history
    )
    if not transcript:
        transcript = "No previous turns yet. This is the opening speech."

    # 5. Fetch Directives
    toolkit = _get_toolkit(side)
    directive = _get_round_directive(current_round, side)

    # 6. Dynamic Prep Instructions
    if current_round == 1 and side == "affirmative":
        prep_instructions = (
            "1. Core Framework: [Plan 3 full contentions with evidence tags — target 800-950 words]\n"
            "2. Pre-emptive Strike: [Plan how to neutralize HARD1/HARD2 using M1/M2]\n"
            "3. Alternative Pre-emption: [Briefly establish why payroll taxes/value capture/parking reform cannot substitute]\n"
            "4. Current-Situation Attack: [Plan 2 ways the current arrangement is worse]\n"
            "5. Closing Phrase: [Draft a unique, memorable closing — avoid 'status quo']"
        )
    elif current_round == 1 and side == "negative":
        prep_instructions = (
            "1. Core Framework: [Open with CONDITIONAL EFFECTIVENESS — mandate assumes uniform readiness]\n"
            "2. Offensive Strike: [Launch IMPLEMENTATION FRAGILITY using HARD1/HARD2]\n"
            "3. AFF Vulnerability: [Identify 1 weakness using COUNTER1/COUNTER2 to preempt]\n"
            "4. Closing Phrase: [Draft a unique closing — avoid generic 'vote negative']"
        )
    elif current_round == 5:
        prep_instructions = (
            "1. Identify 2-3 Voting Issues: [Select the strongest unresolved clashes]\n"
            "2. Plan Meta-Weighing: [Certainty vs. speculation? Magnitude vs. probability?]\n"
            "3. Crystallization Check: [Cut everything that isn't a voting issue or evidence cite]\n"
            "4. Closing Phrase: [Check past closings below — draft something COMPLETELY different]"
        )
    elif side == "affirmative":
        prep_instructions = (
            "1. New Constructive: [What GENUINELY NEW angle can you introduce? Different framing each round]\n"
            "2. Dropped-Claim Check: [One sentence max if opponent claimed we dropped something]\n"
            "3. Alternatives Rebuttal: [New angle on alternatives — don't repeat previous round's rebuttal]\n"
            "4. Opponent's Core Argument: [See opponent key claims below — which is their strongest?]\n"
            "5. Closing Phrase: [Check past closings below — draft something new]"
        )
    else:
        prep_instructions = (
            "1. Opponent's Core Argument: [What is their strongest claim? See opponent key claims below]\n"
            "2. Strategic Rebuttal: [Which pillar/piece of evidence directly answers it? Plan 'Even-If' subsumption]\n"
            "3. Evolution Check: [Am I advancing the argument, or repeating a past round? See past arguments below]\n"
            "4. Closing Phrase: [Check past closings below — draft something new]"
        )

    target_length = (
        "650-800 words of concentrated crystallization."
        if current_round == 5
        else "800-950 words of flowing, persuasive prose."
    )

    # 7. The System Prompt
    system = (
        "You are an expert debate speaker evaluated by an AI judge on five criteria: "
        "grounding in material, logical reasoning, direct clash, no empty repetition, and offensive pressure.\n\n"
        "CORE RULES:\n\n"
        "1. STRICT GROUNDING — Use YOUR OWN evidence tags ([A1], [N1], [M1], [HARD1], [COUNTER1]) from "
        "the Material Evidence Bank below to support your claims.\n"
        "CRITICAL: Your opponent uses a DIFFERENT tag numbering system. Their tags (e.g., [E7], [B15], [F4], etc.) "
        "refer to the same underlying material but with different labels. NEVER claim that an opponent's tag "
        "'does not exist' or is 'ungrounded' based on the tag label alone. If you want to cite the same quote "
        "they referenced, use YOUR OWN corresponding tag. Only challenge a factual claim if the SUBSTANCE of what "
        "they said is genuinely absent from the material — not because their tag format differs from yours.\n\n"
        "2. NO FABRICATION — You may ONLY cite facts, statistics, examples, city names, studies, or outcomes "
        "that are EXPLICITLY present in the Material Evidence Bank below. If the material does not name a "
        "specific city, study, or statistic, you MUST NOT invent one. Instead, argue from the material's "
        "general principles, causal mechanisms, and conditional claims. Violating this rule is the fastest "
        "way to lose a judge's vote.\n\n"
        "3. DIRECT CLASH — Name their specific arguments and answer them directly. If they claim you 'dropped' "
        "an argument, check the transcript. If you addressed it even partially, say so and explain why your "
        "answer was sufficient. Never let a false 'dropped' claim stand uncontested.\n\n"
        "4. NO EMPTY REPETITION — Evolve your arguments every round. Do NOT repeat past points, openers, or closings. "
        "Vary your vocabulary across rounds:\n"
        "- Instead of repeating 'the status quo,' alternate with 'the current arrangement,' 'doing nothing,' "
        "'the existing approach,' 'inaction,' 'the default position,' 'the baseline we are comparing against,' etc.\n"
        "- Instead of repeating 'replaces an invisible cost with a visible one' (or similar metaphors about invisible "
        "taxes/visible prices), find a FRESH way to express the idea that unpriced congestion already imposes costs. "
        "You may express this underlying insight once per round, but NEVER use the same metaphor or sentence "
        "structure twice across the debate. The judge penalizes verbatim repetition of central claims.\n"
        "- Do NOT reuse the label 'triple mechanism' more than once in the entire debate. If you need to refer "
        "to the concept, describe it using different words each time.\n\n"
        "5. CLOSING VARIATION — Use a different final sentence every round. Check your past closings and avoid any "
        "similarity in wording or imagery.\n\n"
        "6. MEASURED TONE — Speak conversationally and persuasively. No aggressive jargon ('destroyed', 'fallacy', "
        "'strawman'). No bold text, no bullet points, no markdown headers in the speech itself.\n\n"
        "OUTPUT FORMAT:\n"
        "<prep>\n"
        f"{prep_instructions}\n"
        "</prep>\n"
        "<speech>\n"
        f"Your final spoken words. Target: {target_length}\n"
        "</speech>"
    )

    # Build the fabrication reminder — placed in user prompt for maximum salience
    if current_round == 1:
        fabrication_reminder = ""
    else:
        fabrication_reminder = (
            "\n\n=== REPEATED REMINDER: NO FABRICATION ===\n"
            "Do NOT name specific cities (London, Stockholm, Singapore, Milan, New York, etc.), "
            "specific statistics, or specific study outcomes unless they are EXPLICITLY quoted in the "
            "Material Evidence Bank above. If you are unsure whether the material mentions a specific name "
            "or number, do NOT include it. Argue from principles and mechanisms instead."
        )

    user = (
        f"Motion: {material.topic}\n\n"
        f"Material Evidence Bank:\n{material_map}\n\n"
        f"{fabrication_reminder}"
        f"Transcript (Last {MAX_TURNS} turns):\n{transcript}\n\n"
        f"--- YOUR PAST ARGUMENTS (DO NOT REPEAT THESE POINTS) ---\n"
        f"{past_arguments}\n\n"
        f"--- YOUR PAST STRUCTURAL FRAMES (VARY YOUR OPENERS) ---\n"
        f"{structural_frames}\n\n"
        f"--- YOUR PAST CLOSINGS (USE A DIFFERENT CLOSING EVERY ROUND) ---\n"
        f"{past_closings}\n\n"
        f"--- OPPONENT'S KEY ARGUMENTS (CLASH THESE DIRECTLY) ---\n"
        f"{opponent_key_args}\n\n"
        f"Side: {side.upper()}\n"
        f"Toolkit: {toolkit}\n"
        f"Directive: {directive}\n\n"
        "Execute your <prep> block, then deliver your <speech>."
    )

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
