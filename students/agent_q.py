from debate_eval.api import chat

DEBATER_SYSTEM_PROMPT = """# System Directive
You are an elite, logic-driven Debate Agent participating in a competitive format. Your primary objective is to persuade the judges by constructing mathematically airtight arguments and systematically dismantling the opponent's core premises. You prioritize structural logic over rhetorical fluff.

# Execution Pipeline
For every turn in the debate, you must process the input through the following internal pipeline before generating your spoken output.

## Step 1: State the Axiom (Architecture)
*   **Define the Framework:** Identify the core terms of the current topic. Define them in a way that establishes the boundaries of the debate in our favor.
*   **Establish the Axiom:** Formulate the bedrock premise of our argument that the audience will implicitly accept as true.
*   **Rule of Three:** Group your active arguments for this turn into exactly three distinct, digestible pillars.

## Step 2: Internal Simulation (Defense & Anticipation)
*   **Steelman the Opponent:** Internally generate the strongest, most charitable version of the opponent's argument. Do not misrepresent them.
*   **Multi-Turn Anticipation:** Project the next two steps of the debate tree. If you make point X, what are their top two counter-arguments?
*   **Pre-computation:** Formulate the rebuttals to those counter-arguments and weave them into your current defense as preemptive strikes.

## Step 3: Strategic Offense (Dismantling)
*   **Attack the Link:** Do not waste tokens attacking the *impact* of their claims. Attack the causal mechanism. Prove that their proposed action does not lead to their stated outcome.
*   **The "Even If" Protocol (Subsumption):** Formulate a condition where, even if the opponent's core premise is granted as 100% true, their conclusion still structurally fails or is subsumed by our framework.
*   **Fallacy Check:** Scan their previous turn for false dichotomies, strawmen, or moving the goalposts. Tag them for exposure.

## Step 4: Output Generation (Delivery)
Draft the final response using the following constraints:
*   **Signposting:** Begin every major paragraph with a clear structural marker (e.g., "On the opponent's first contention regarding...", "Moving to our second pillar...").
*   **Pacing:** Group rapid-fire points from the opponent into single thematic vulnerabilities. Dismantle the theme, not the individual noise.
*   **Concession:** Identify one trivial, low-impact point from the opponent to explicitly concede, optimizing for perceived intellectual honesty and credibility.

# Burden of Proof
If you are the AFFIRMATIVE side: you bear the burden to prove the motion is necessary and superior to alternatives. Never argue "the burden is on them to disprove" — judges read this as evasion of your own burden.
If you are the NEGATIVE side: you only need to raise reasonable doubt about the motion's necessity or superiority. You do not need to propose a perfect alternative.

# Output Format
Output ONLY the final generated speech. Do not output your internal reasoning pipeline, the simulation tree, or meta-commentary. Keep the tone authoritative, methodically paced, and relentlessly logical."""


def speak(material, history, side):
    current_round = (len(history) // 2) + 1
    opponent_side = "negative" if side == "affirmative" else "affirmative"

    transcript = "\n".join(
        f"Round {turn.round_index} {turn.side}: {turn.content}" for turn in history
    ) or "No previous turns yet."

    shared_context = (
        f"Motion: {material.topic}\n\n"
        f"Material:\n{material.content}\n\n"
        f"Transcript so far:\n{transcript}"
    )

    # --- Call 0: Material Grounding ---
    grounded_facts = chat([
        {
            "role": "system",
            "content": "You are a precise research analyst. Your only job is to extract verifiable facts from provided text.",
        },
        {
            "role": "user",
            "content": (
                f"Read the following material carefully.\n\n"
                f"Material:\n{material.content}\n\n"
                "Extract every fact, statistic, city example, policy outcome, and causal claim "
                "that is EXPLICITLY stated in this material. "
                "Do not infer, extrapolate, or add any outside knowledge. "
                "Output a numbered list. Each item must be a single, specific, verifiable claim directly from the text."
            ),
        },
    ])

    # --- Call 1: Debate Arc Analysis ---
    if len(history) == 0:
        arc_analysis = (
            "This is the opening speech. Establish the foundational framework and preemptively "
            "inoculate against the most obvious counterarguments."
        )
    else:
        our_speeches = [t for t in history if t.side == side]
        our_prior_arguments = "\n".join(
            f"Round {t.round_index}: {t.content[:600]}..." for t in our_speeches
        ) or "None yet."
        last_opponent_speech = history[-1].content

        arc_analysis = chat([
            {
                "role": "system",
                "content": "You are a master debate strategist and logician.",
            },
            {
                "role": "user",
                "content": (
                    f"{shared_context}\n\n"
                    f"The opponent ({opponent_side}) just gave this speech:\n'{last_opponent_speech}'\n\n"
                    f"Our side's prior arguments (summaries):\n{our_prior_arguments}\n\n"
                    "Produce a structured strategic brief with exactly five sections:\n"
                    "1. OPPONENT WEAKNESSES: The 3 weakest logical or evidential links in the opponent's last speech.\n"
                    "2. OUR STANDING ARGUMENTS: Which of our side's arguments remain unrefuted by the opponent.\n"
                    "3. DROPPED ARGUMENTS: What arguments from our previous speeches did the opponent FAIL to address in their last turn? "
                    "These are conceded by silence and must be capitalized on.\n"
                    "4. KEY CLASH: The single most important unresolved point of contention right now.\n"
                    "5. THIS ROUND'S MISSION: What this speech must accomplish to advance our position in the overall arc.\n"
                    "Be concise, analytical, and ruthlessly critical."
                ),
            },
        ])

    # --- Call 2: Draft Speech ---
    if current_round == 1:
        round_instruction = (
            "This is your opening speech. Establish the foundational framework and preemptively inoculate "
            "against obvious counterarguments. Open with a strong affirmative claim, not a reactive frame. "
            "Do not waste time rebutting arguments that haven't been made yet."
        )
    elif current_round == 5:
        round_instruction = (
            "This is Round 5, your FINAL closing speech. DO NOT introduce any new arguments. "
            "DO NOT summarize all five rounds — that is not a closing argument, it is a table of contents. "
            "Instead: identify the 2 most important clash points that your side has won and explain WHY "
            "winning those specific points wins the overall debate (impact weighing). "
            "Use the 'Even If' framing: 'Even if the judges grant the opponent X, we still win because...' "
            "Make a judge-facing closing argument that crystallizes why your side prevails on what matters most."
        )
    else:
        round_instruction = (
            f"This is Round {current_round} of 5. "
            "STRUCTURE: spend no more than 40% of the speech rebutting the opponent's last speech. "
            "Spend at least 60% advancing a NEW constructive argument not yet made in this debate. "
            "Do NOT open with reactive framing like 'their pillars crumble' — open with a new affirmative claim. "
            "Explicitly capitalize on any DROPPED ARGUMENTS listed in the strategic brief, "
            "as the opponent's silence on those points constitutes a concession."
        )

    draft = chat([
        {
            "role": "system",
            "content": (
                DEBATER_SYSTEM_PROMPT + "\n\n"
                f"You are representing the {side} side. "
                "Your tone must be academic, measured, and authoritative. "
                "Rely strictly on logic and the provided material.\n\n"
                "CRITICAL EVIDENCE RULE: You may ONLY cite specific facts, statistics, city examples, "
                "or policy outcomes that appear in the GROUNDED FACTS LIST provided below. "
                "Do not invent, embellish, or cite any case, number, or program not on that list. "
                "If you need to support a logical point without a grounded fact, argue from principle — "
                "never from fabricated specifics."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{shared_context}\n\n"
                f"--- GROUNDED FACTS (cite ONLY these as evidence) ---\n{grounded_facts}\n\n"
                f"--- STRATEGIC BRIEF ---\n{arc_analysis}\n\n"
                f"--- ROUND INSTRUCTIONS ---\n{round_instruction}\n\n"
                "Write the full draft speech in English. "
                "Do NOT output meta-text, round numbers, headers, or section labels. "
                "Do NOT exceed 7000 characters."
            ),
        },
    ])

    # --- Call 3: Adversarial Red-Team + Revision ---
    final_speech = chat([
        {
            "role": "system",
            "content": (
                "You are performing a two-phase task.\n\n"
                "PHASE 1 — Adversarial Attack: Adopt the persona of the opposing debater. "
                "Attack the draft speech ruthlessly. Find every claim that is factually shaky or unsupported "
                "by the grounded facts list, every burden-shift evasion, every unsupported generalization, "
                "and every missed rebuttal opportunity from the strategic brief. "
                "Identify your 3 strongest attacks.\n\n"
                "PHASE 2 — Revision: Switch back to being the original debater. "
                "Revise the draft to preemptively address those 3 attacks while preserving everything strong. "
                "Output ONLY the final revised speech — no Phase 1 commentary, no headers, no meta-text.\n\n"
                "HARD CONSTRAINTS on the final output:\n"
                "- Do NOT add any headers, round labels, 'Closing Statement', or meta-text of any kind.\n"
                "- Do NOT introduce any new factual claims not already in the draft or the grounded facts list.\n"
                "- Preserve the speech's opening sentence — do not replace it with a reactive or summary opener.\n"
                "- The final speech must be in English and must not exceed 7000 characters."
            ),
        },
        {
            "role": "user",
            "content": (
                f"--- GROUNDED FACTS (only these may be cited as evidence) ---\n{grounded_facts}\n\n"
                f"--- STRATEGIC BRIEF ---\n{arc_analysis}\n\n"
                f"--- ROUND INSTRUCTIONS ---\n{round_instruction}\n\n"
                f"--- DRAFT SPEECH TO RED-TEAM AND REVISE ---\n{draft}\n\n"
                "Execute Phase 1 (attack), then Phase 2 (revise). "
                "Output ONLY the final revised speech."
            ),
        },
    ])

    return final_speech
