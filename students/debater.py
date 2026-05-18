from __future__ import annotations

import hashlib
import json
import re

from debate_eval.api import chat


MAX_SAFE_CHARS = 6600
MAX_TRANSCRIPT_CHARS = 11000
MAX_FULL_MATERIAL_CHARS = 14000
MAX_MATERIAL_MAP_CHARS = 5200
MAX_STRATEGY_CHARS = 5200

_MATERIAL_MAP_CACHE = {}

_BACKUP_ANCHOR_SPECS = [
    ("price signals", "Pricing directly rations scarce road space.", "affirmative offense"),
    ("dedicated revenue", "Pricing creates transit funding.", "affirmative offense"),
    ("serious equity dilemma", "Equity is a central clash.", "both weighing"),
    ("low-income workers", "Fees may burden vulnerable commuters.", "negative offense"),
    ("slow, unreliable, unsafe, or inaccessible", "Bad alternatives can make pricing punitive.", "negative offense"),
    ("too many carve-outs", "Exemptions can weaken revenue and traffic reduction.", "negative offense"),
    ("near capacity", "Transit readiness is a central risk.", "negative offense"),
    ("restaurants, shops, and cultural venues", "Business loss is a material-supported risk.", "negative offense"),
    ("businesses benefit", "Business reliability is a material-supported affirmative answer.", "affirmative defense"),
    ("Trust is crucial", "Revenue governance and public trust matter.", "negative offense"),
    ("geographic politics", "Local coalition-building is difficult.", "negative offense"),
    ("two imperfect models of fairness", "The final weighing is comparative, not perfect-policy.", "both weighing"),
]


def _current_round(history, side):
    return sum(1 for turn in history if turn.side == side) + 1


def _opponent_side(side):
    return "negative" if side == "affirmative" else "affirmative"


def _side_stance(side):
    if side == "affirmative":
        return "support the motion"
    return "oppose the motion"


def _side_strategy(side):
    if side == "affirmative":
        return (
            "Affirmative strategy: defend a reasonable implementation of the required policy, "
            "not a deliberately broken version. Treat transparent revenue use, targeted hardship "
            "relief, privacy safeguards, and phased rollout as normal implementation choices. "
            "Do not overclaim that there is zero burden; instead prove that congestion already "
            "imposes worse time, health, and transit-underfunding costs, while pricing creates a "
            "mechanism to reduce and reinvest those costs. Against 'transit first', press that "
            "the opponent has no equally stable funding mechanism and no direct price signal. "
            "Against alternative portfolios such as fuel taxes, parking fees, payroll levies, "
            "or registration fees, use this fork: if they are not time-and-zone specific, they "
            "do not price the central-business-district congestion externality; if they are "
            "time-and-zone specific, they approximate congestion pricing while inheriting similar "
            "administrative and equity tradeoffs. Do not dismiss plausible alternatives merely "
            "because the material does not list them; grant that they may help, then argue they "
            "are either less targeted or not meaningfully distinct from pricing. Against the "
            "sequencing gap, do not claim transit can be built instantly. Argue comparatively: "
            "the negative's transit-first world still needs an upfront funding and political "
            "mechanism, while pricing creates a dedicated mechanism that can be phased, targeted "
            "to bus speed/frequency/fare relief first, and escalated only as alternatives improve."
        )
    return (
        "Negative strategy: make the mandate look too blunt for diverse cities. Press the structural "
        "tensions in the material: exemptions versus effectiveness, charging before transit capacity, "
        "business uncertainty, privacy/enforcement, and public trust. Do not sound anti-transit or "
        "pro-gridlock; defend sequencing, local readiness, and targeted alternatives."
    )


def _stage_guidance(round_number):
    if round_number <= 1:
        return (
            "This is the opening speech for this side. Build a clear case with "
            "exactly three major arguments, use only the material provided, and "
            "preempt the most likely opposing response. For affirmative, preempt "
            "sequencing, alternative funding portfolios, and mandate heterogeneity. "
            "For negative, preempt the claim that waiting simply preserves gridlock."
        )
    if round_number <= 3:
        return (
            "This is a middle speech. Prioritize direct rebuttal of the opponent, "
            "then extend the strongest surviving arguments for this side."
        )
    if round_number == 4:
        return (
            "This is a late speech. Compare both worlds, weigh impacts, and show "
            "why this side is winning the central clashes."
        )
    return (
        "This is the final speech. Crystallize the debate into two or three "
        "voting issues, answer the opponent's best material, and explain why the "
        "judge should vote for this side. Be shorter than earlier speeches and avoid "
        "repeating old paragraphs."
    )


def _format_history(history):
    if not history:
        return "No previous turns yet."

    parts = []
    for turn in history:
        parts.append(
            f"Round {turn.round_index} | {turn.side} | {turn.speaker}\n{turn.content}"
        )
    transcript = "\n\n".join(parts)
    if len(transcript) <= MAX_TRANSCRIPT_CHARS:
        return transcript
    return "[Earlier transcript omitted to fit context]\n" + transcript[-MAX_TRANSCRIPT_CHARS:]


def _safe_trim(text):
    text = _clean_speech(text)
    if len(text) <= MAX_SAFE_CHARS:
        return text

    trimmed = text[:MAX_SAFE_CHARS].rstrip()
    paragraph_cut = trimmed.rfind("\n\n")
    if paragraph_cut > MAX_SAFE_CHARS * 0.75:
        trimmed = trimmed[:paragraph_cut].rstrip()
    return trimmed


def _clean_speech(text):
    text = str(text or "").strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lower = text.lower()
    if "</think>" in lower:
        text = text[lower.rfind("</think>") + len("</think>") :]
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    text = re.sub(r"(?is)</?think>", "", text)
    text = re.sub(r"(?im)^\s*round\s+\d+\s*\|\s*(affirmative|negative)\s*\|.*$", "", text)
    text = re.sub(r"(?im)^\s*side:\s*(affirmative|negative)\s*$", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?i)\bmaterial map\b", "supplied material", text)
    text = re.sub(r"(?i)\bevidence summary\b", "supplied material", text)
    text = re.sub(r"\b((?:\w+\s+){0,3}\w+)[\"'”’]\s*\1\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\w+(?:\s+\w+){0,3})\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    text = text.replace("**On equity:*", "On equity:")
    text = text.replace("Madam/Mister", "Chair")
    replacements = {
        "provides only stated only": "provides only",
        "does not yet and waiting": "does not yet exist",
        "transit remains transit underfunded": "transit remains underfunded",
        "status quo fails to fund transit funding": "status quo fails to fund transit",
        "administrantly": "administratively",
        "to the tools to": "the tools to",
        "if you charge before capacity does not exist": "if you charge before capacity exists",
        "as a providing a fiscal tool": "as providing a fiscal tool",
        "supported by the supplied in the material": "supported by the supplied material",
        "can set a fixed, transparent cap on exemptions is": "can set a fixed, transparent cap on exemptions as",
        "hollow out both hollow out both": "hollow out both",
    }
    for bad, good in replacements.items():
        text = re.sub(re.escape(bad), good, text, flags=re.IGNORECASE)
    return text.strip()


def _call(messages):
    return chat(messages).strip()


def _json_dumps(value, max_chars=None):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def _extract_json_object(text):
    text = str(text or "").strip()
    if not text:
        return None

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    candidates = [text]
    if fenced:
        candidates.insert(0, fenced.group(1))

    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break

    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    return None


def _as_list(value, limit=5):
    if isinstance(value, list):
        return [str(item)[:500] for item in value[:limit]]
    if isinstance(value, str) and value.strip():
        return [value.strip()[:500]]
    return []


def _fallback_material_map(material):
    return {
        "key_points": [
            {
                "id": "K1",
                "claim": "Use the material's stated tradeoffs, risks, and benefits as the evidence base.",
                "helps_side": "both",
                "importance": 5,
            }
        ],
        "evidence_bank": [],
        "best_aff_cases": [
            "Congestion pricing can reduce congestion, improve transit funding, and address environmental harms."
        ],
        "best_neg_cases": [
            "Congestion pricing can be regressive, premature without transit capacity, and hard to implement fairly."
        ],
        "likely_clashes": [
            "efficiency versus equity",
            "revenue for transit versus charging before alternatives exist",
            "policy design versus mandate risk",
        ],
        "danger_zones": [
            "Do not invent city statistics, exact percentages, or studies unless they appear in the material or transcript."
        ],
        "weighing_axes": ["fairness", "feasibility", "implementation risk", "long-term mobility"],
    }


def _normalize_for_match(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _find_material_anchor(material_text, keyword, max_len=180):
    text = str(material_text or "")
    lower = text.lower()
    index = lower.find(str(keyword or "").lower())
    if index < 0:
        return ""

    sentence_start = max(
        text.rfind(".", 0, index),
        text.rfind("!", 0, index),
        text.rfind("?", 0, index),
        text.rfind("\n", 0, index),
    )
    sentence_start = 0 if sentence_start < 0 else sentence_start + 1

    sentence_ends = [
        pos for pos in (
            text.find(".", index),
            text.find("!", index),
            text.find("?", index),
            text.find("\n", index),
        )
        if pos >= 0
    ]
    sentence_end = min(sentence_ends) + 1 if sentence_ends else len(text)
    anchor = text[sentence_start:sentence_end].strip()

    if len(anchor) > max_len:
        if index - sentence_start <= 105:
            start = sentence_start
        else:
            start = max(0, index - 105)
        end = min(sentence_end, start + max_len)
        if end < index + len(keyword) + 40:
            end = min(sentence_end, index + len(keyword) + 80)
        if start > 0:
            next_space = text.find(" ", start, index)
            if next_space > 0:
                start = next_space + 1
        if end < len(text):
            prev_space = text.rfind(" ", index, end)
            if prev_space > index:
                end = prev_space
        anchor = text[start:end].strip()
    return anchor[:max_len].strip()


def _add_backup_anchors(material, anchors):
    material_norm = _normalize_for_match(material.content)
    seen = {_normalize_for_match(item.get("anchor", "")) for item in anchors if isinstance(item, dict)}
    result = list(anchors)

    for keyword, supports, use_for in _BACKUP_ANCHOR_SPECS:
        if keyword.lower() not in material_norm:
            continue
        if any(keyword.lower() in item.get("anchor", "").lower() for item in result):
            continue
        anchor = _find_material_anchor(material.content, keyword)
        if not anchor or _normalize_for_match(anchor) not in material_norm:
            continue
        anchor_norm = _normalize_for_match(anchor)
        if anchor_norm in seen:
            continue
        seen.add(anchor_norm)
        result.append(
            {
                "id": f"B{len(result) + 1}",
                "anchor": anchor,
                "supports": supports,
                "use_for": use_for,
            }
        )
    return result


def _validate_material_map(material, material_map):
    if not isinstance(material_map, dict):
        return _fallback_material_map(material)

    validated = dict(material_map)
    material_norm = _normalize_for_match(material.content)

    exact_anchors = []
    for item in material_map.get("evidence_bank", []) if isinstance(material_map.get("evidence_bank"), list) else []:
        if not isinstance(item, dict):
            continue
        anchor = str(item.get("anchor") or item.get("quote") or "").strip()
        if not anchor:
            continue
        if _normalize_for_match(anchor) not in material_norm:
            continue
        exact_anchors.append(
            {
                "id": str(item.get("id", f"E{len(exact_anchors) + 1}"))[:12],
                "anchor": anchor[:180],
                "supports": str(item.get("supports", ""))[:240],
                "use_for": str(item.get("use_for", ""))[:80],
            }
        )

    exact_anchors = _add_backup_anchors(material, exact_anchors)
    validated["key_points"] = material_map.get("key_points", [])[:10] if isinstance(material_map.get("key_points"), list) else []
    validated["evidence_bank"] = exact_anchors[:18]
    validated["best_aff_cases"] = _as_list(material_map.get("best_aff_cases"), 6)
    validated["best_neg_cases"] = _as_list(material_map.get("best_neg_cases"), 6)
    validated["likely_clashes"] = _as_list(material_map.get("likely_clashes"), 7)
    validated["danger_zones"] = _as_list(material_map.get("danger_zones"), 8)
    validated["weighing_axes"] = _as_list(material_map.get("weighing_axes"), 6)
    return validated


def _material_cache_key(material):
    raw = f"{material.topic}\n{material.content}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def _material_map_prompt(material):
    return [
        {
            "role": "system",
            "content": (
                "You compress debate source material into a compact evidence map. "
                "Return strict JSON only. Use no outside facts. Every anchor must be an exact "
                "short substring copied from the supplied material."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Motion:\n{material.topic}\n\n"
                f"Material:\n{material.content}\n\n"
                "Create this JSON object:\n"
                "{"
                '"key_points":[{"id":"K1","claim":"...","helps_side":"affirmative|negative|both","importance":1}],'
                '"evidence_bank":[{"id":"E1","anchor":"short material phrase, max 150 chars","supports":"...","use_for":"offense|defense|weighing"}],'
                '"best_aff_cases":["..."],'
                '"best_neg_cases":["..."],'
                '"likely_clashes":["..."],'
                '"danger_zones":["unsupported claims or tempting outside facts to avoid"],'
                '"weighing_axes":["fairness","feasibility","long-term impact"]'
                "}\n"
                "Limits: 6-10 key_points, 6-12 evidence_bank anchors, 4-7 likely_clashes. "
                "Prefer exact material phrases that can be reused by both sides. No markdown."
            ),
        },
    ]


def _get_material_map(material):
    key = _material_cache_key(material)
    cached = _MATERIAL_MAP_CACHE.get(key)
    if cached is not None:
        return cached

    parsed = _extract_json_object(_call(_material_map_prompt(material)))
    if not parsed:
        parsed = _fallback_material_map(material)
    parsed = _validate_material_map(material, parsed)
    _MATERIAL_MAP_CACHE[key] = parsed
    return parsed


def _strategy_prompt(material, side, round_number, transcript, material_map):
    hard_turn_note = (
        "This is a hard late turn: avoid repeating earlier speeches verbatim. "
        "Collapse to decisive voting issues and make the final comparison easy for the judge."
        if round_number >= 4
        else "This is not yet the final collapse: prioritize live clash and useful extensions."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a private debate strategist. Return strict JSON only, not a speech. "
                "Use the full supplied material as the source of truth; the evidence summary is only "
                "an index. Identify unsupported opponent claims only when they are precise numbers, "
                "named city outcomes, named studies, timelines, or institutional details that are "
                "absent from the full supplied material and transcript. Do not flag broad claims that "
                "the full material itself supports."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Motion:\n{material.topic}\n\n"
                f"Side: {side}\n"
                f"Speech number for this side: {round_number} of 5\n"
                f"Round role: {_stage_guidance(round_number)}\n"
                f"Side strategy: {_side_strategy(side)}\n"
                f"{hard_turn_note}\n\n"
                f"Full supplied material for support checks:\n{material.content[:MAX_FULL_MATERIAL_CHARS]}\n\n"
                f"Supplied evidence summary JSON:\n{_json_dumps(material_map, MAX_MATERIAL_MAP_CHARS)}\n\n"
                f"Transcript:\n{transcript}\n\n"
                "Return this JSON object:\n"
                "{"
                '"debate_state":{'
                '"our_committed_claims":["..."],'
                '"opponent_latest_claims":["..."],'
                '"opponent_strongest_live_claim":"...",'
                '"unanswered_attacks_on_us":["..."],'
                '"our_best_winning_issues":["..."],'
                '"claims_we_should_not_repeat":["..."],'
                '"unsupported_or_overclaimed_opponent_points":["only precise outside statistics, named examples, studies, timelines, or institutional details"],'
                '"unsafe_new_claims":["..."],'
                '"next_turn_goal":"frame|rebuttal|extension|crystallization"'
                "},"
                '"candidate_outlines":['
                '{"name":"rebuttal_heavy","thesis":"...","structure":["..."],"must_answer":["..."],"material_anchors":["E1"],"main_voting_issue":"..."},'
                '{"name":"weighing_heavy","thesis":"...","structure":["..."],"must_answer":["..."],"material_anchors":["E2"],"main_voting_issue":"..."}'
                "],"
                '"selected_outline":{'
                '"name":"rebuttal_heavy|weighing_heavy",'
                '"why_selected":["..."],'
                '"thesis":"...",'
                '"must_answer":["..."],'
                '"material_anchors":["E1"],'
                '"unsupported_claims_to_challenge":["..."],'
                '"anti_repetition_plan":["..."],'
                '"closing_voting_issues":["..."]'
                "}"
                "}\n"
                "Rules: choose the outline most likely to win under grounding, logic, rebuttal, "
                "consistency, and clash. If the opponent used unsupported precise facts, plan an "
                "explicit grounding challenge. Before doing so, check the full supplied material. "
                "If the opponent's claim is directly supported, broadly paraphrased, or framed as a "
                "risk in the full material, answer it on the merits instead of calling it unsupported. "
                "Do not plan weak exact-wording attacks such as 'the phrase is not used' when the "
                "idea appears in the material. The better answer is usually that the material presents "
                "the point as a risk, tradeoff, or supporter/critic argument rather than a decisive fact. "
                "No public speech prose."
            ),
        },
    ]


def _fallback_strategy(side, round_number):
    if side == "affirmative":
        strongest = "The opponent says pricing charges before alternatives exist."
        answer = "The material treats pricing as a funding and behavior mechanism, so the status quo also has costs."
    else:
        strongest = "The opponent says design and revenue solve the policy's harms."
        answer = "The material warns that design fixes create tradeoffs around transit capacity, exemptions, trust, and implementation."
    return {
        "debate_state": {
            "our_committed_claims": [],
            "opponent_latest_claims": [strongest],
            "opponent_strongest_live_claim": strongest,
            "unanswered_attacks_on_us": [strongest],
            "our_best_winning_issues": [answer],
            "claims_we_should_not_repeat": [],
            "unsupported_or_overclaimed_opponent_points": [],
            "unsafe_new_claims": [],
            "next_turn_goal": "crystallization" if round_number >= 5 else "rebuttal",
        },
        "selected_outline": {
            "name": "fallback",
            "why_selected": ["It directly answers the strongest live clash."],
            "thesis": answer,
            "must_answer": [strongest],
            "material_anchors": [],
            "unsupported_claims_to_challenge": [],
            "anti_repetition_plan": ["Use a shorter structure and avoid repeating old paragraphs."],
            "closing_voting_issues": [answer],
        },
    }


def _get_strategy(material, side, round_number, transcript, material_map):
    parsed = _extract_json_object(
        _call(_strategy_prompt(material, side, round_number, transcript, material_map))
    )
    if not parsed:
        parsed = _fallback_strategy(side, round_number)
    parsed.setdefault("debate_state", {})
    parsed.setdefault("selected_outline", {})
    return parsed


def _analysis_prompt(material, history, side, round_number, transcript):
    return [
        {
            "role": "system",
            "content": (
                "You are the private strategist for a debate agent. Produce compact strategic notes, "
                "not the public speech. Use only the supplied material and transcript. Do not invent "
                "external examples, statistics, or studies."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Motion:\n{material.topic}\n\n"
                f"Material:\n{material.content}\n\n"
                f"Side: {side}\n"
                f"Speech number for this side: {round_number} of 5\n"
                f"{_side_strategy(side)}\n\n"
                f"Transcript:\n{transcript}\n\n"
                "Create a concise plan with these headings:\n"
                "1. Judge ballot route: one sentence on how this side wins under material grounding, "
                "logic, rebuttal, consistency, and clash.\n"
                "2. Opponent's strongest live claims, if any.\n"
                "3. Our best answers to those claims.\n"
                "4. Best offensive extensions from the material.\n"
                "5. Risks to avoid: hallucinations, concessions, repetition, weak weighing.\n"
                "Keep under 1200 words."
            ),
        },
    ]


def _draft_prompt(material, side, round_number, transcript, material_map, strategy):
    strategy_text = _json_dumps(strategy, MAX_STRATEGY_CHARS)
    material_text = _json_dumps(material_map, MAX_MATERIAL_MAP_CHARS)
    if round_number >= 5:
        target_length = "4300-5200"
    elif round_number == 1 and side == "affirmative":
        target_length = "5800-6400"
    else:
        target_length = "5400-6200"
    final_round_rule = (
        "Round 5 rule: do not repeat earlier paragraphs. Collapse to exactly two voting "
        "issues plus a short final comparative paragraph. "
        if round_number >= 5
        else ""
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a strong English-language tournament debater. Write the public speech only. "
                f"You are {side}; never switch sides. The judge values material grounding, clear "
                "logic, direct rebuttal, consistency, and comparative weighing. Do not reveal private "
                "planning. Do not include transcript metadata. Use the full supplied material as the "
                "source of truth. If the opponent used precise facts or statistics not grounded in the "
                "full material or transcript, challenge their grounding instead of treating those claims "
                "as true. Do not attack a broad material-supported risk as unsupported. Do not use the "
                "terms 'material map' or 'evidence summary' in the public speech; say 'the supplied "
                "material' or 'the material'."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Motion:\n{material.topic}\n\n"
                f"Full supplied material for support checks:\n{material.content[:MAX_FULL_MATERIAL_CHARS]}\n\n"
                f"Supplied evidence summary:\n{material_text}\n\n"
                f"Side: {side}\n"
                f"Speech number: {round_number} of 5\n"
                f"Round role: {_stage_guidance(round_number)}\n"
                f"Side strategy: {_side_strategy(side)}\n\n"
                f"Transcript:\n{transcript}\n\n"
                f"Private strategy JSON:\n{strategy_text}\n\n"
                f"{final_round_rule}"
                f"Write the next speech in {target_length} characters.\n"
                "Requirements:\n"
                "- Use only facts, examples, and tensions present in the full supplied material, evidence summary, or transcript.\n"
                "- Use 2-4 exact material anchors, preferably with wording like "
                "'the material warns', 'the material notes', or 'the material frames'.\n"
                "- Directly rebut the strongest live opponent claims.\n"
                "- Before saying a claim is unsupported, check the full supplied material. If it appears "
                "there directly or as a broad paraphrase, concede the grounding and answer the logic.\n"
                "- Challenge only unsupported precise statistics, named case outcomes, named studies, "
                "timelines, or institutional details. Do not call a broad claim unsupported if the "
                "full supplied material supports it in general.\n"
                "- Do not make exact-wording attacks such as 'that phrase is not in the material' unless "
                "the opponent's argument depends on the exact wording. If the idea appears in the material, "
                "say it is only a risk, contested point, or one side of the tradeoff.\n"
                "- If this is affirmative round 1, build three full contentions: direct congestion mechanism, "
                "transit funding/sequencing mechanism, and fairness/environment/business weighing. Preempt "
                "alternative portfolios and mandate heterogeneity explicitly.\n"
                "- If the opponent offers fuel taxes, parking fees, bonds, payroll levies, registration fees, "
                "or similar alternatives, do not dismiss them as absent from the material. Compare mechanism: "
                "not time-zone specific means less targeted; time-zone specific means close to congestion "
                "pricing and shares its tradeoffs.\n"
                "- Use quotation marks only for exact material anchors. If wording is an inference, "
                "paraphrase without quotation marks.\n"
                "- Make the comparative voting reason explicit.\n"
                "- If affirmative, do not concede that safeguards are outside the policy; defend them "
                "as reasonable implementation of the required policy.\n"
                "- If negative, do not defend the status quo as perfect; defend better sequencing and "
                "local readiness.\n"
                "- In round 5, collapse to two or three voting issues. If affirmative, preempt the "
                "likely final negative close. If negative, use the final word to close the decisive clash.\n"
                "- Avoid ceremonial filler, malformed headings, duplicated phrases, and markdown tables."
            ),
        },
    ]


def _revision_prompt(material, side, round_number, material_map, strategy, draft):
    target_limit = "5200" if round_number >= 5 else "6200"
    final_round_revision = (
        "- for round 5, collapse to exactly two voting issues plus a short final comparison;\n"
        if round_number >= 5
        else ""
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a strict final editor and judge-rubric critic for a debate speech. "
                "Return only the revised public speech. Do not add new facts. Preserve the side "
                "and argument direction. Use the full supplied material as the support-check source "
                "of truth. Never output the terms 'material map' or 'evidence summary'."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Motion:\n{material.topic}\n\n"
                f"Side: {side}\n"
                f"Speech number: {round_number} of 5\n\n"
                f"Full supplied material for support checks:\n{material.content[:MAX_FULL_MATERIAL_CHARS]}\n\n"
                f"Supplied evidence summary:\n{_json_dumps(material_map, MAX_MATERIAL_MAP_CHARS)}\n\n"
                f"Private strategy JSON:\n{_json_dumps(strategy, MAX_STRATEGY_CHARS)}\n\n"
                f"Draft:\n{draft}\n\n"
                f"Revise the speech under {target_limit} characters. Fix these issues:\n"
                "- remove transcript labels or meta-commentary;\n"
                "- remove any hidden-reasoning tags or leaked private thinking;\n"
                "- remove duplicated words, duplicated claims, and malformed headings;\n"
                "- remove the terms 'material map' and 'evidence summary'; use 'supplied material' instead;\n"
                "- remove outside examples/statistics not grounded in the supplied material or transcript;\n"
                "- remove any false accusation that an opponent claim is absent from the material when the full material supports it directly or broadly;\n"
                "- avoid exact-wording attacks; if a broad idea appears in the full material, answer its weight instead of saying the phrase is absent;\n"
                "- keep a grounding challenge only for unsupported precise statistics, named case outcomes, studies, timelines, or institutional details;\n"
                "- do not call broad business, trust, efficiency, equity, or transit claims unsupported when the full supplied material supports them generally;\n"
                "- use quotation marks only for exact material anchors; paraphrase inferred ideas without quotation marks;\n"
                "- sharpen direct rebuttal and final weighing;\n"
                "- cut summary and ceremonial filler before cutting clash;\n"
                "- avoid repeating the same wording from earlier rounds when a shorter voting-issue collapse works;\n"
                f"{final_round_revision}"
                "- keep plain persuasive debate prose."
            ),
        },
    ]


def _fallback_speech(material, side, round_number):
    stance = _side_stance(side)
    opponent = _opponent_side(side)
    return (
        f"We {stance} on the motion: {material.topic}.\n\n"
        "The judge should focus on the practical comparison created by the "
        "material. Our side offers the more coherent response to the tradeoffs "
        "described there: it handles the main harms, explains the mechanism for "
        "change, and avoids relying on assumptions that the evidence does not "
        "support.\n\n"
        f"Against the {opponent}, we maintain that their case either understates "
        "the central risk or overstates the effectiveness of their alternative. "
        "The better ballot is for our side because it is more grounded in the "
        f"motion, more consistent across round {round_number}, and more persuasive "
        "on the most important impacts."
    )


def speak(material, history, side):
    round_number = _current_round(history, side)
    transcript = _format_history(history)

    try:
        material_map = _get_material_map(material)
        strategy = _get_strategy(material, side, round_number, transcript, material_map)
        draft = _call(
            _draft_prompt(material, side, round_number, transcript, material_map, strategy)
        )
        revised = _call(
            _revision_prompt(material, side, round_number, material_map, strategy, draft)
        )
        return _safe_trim(revised)
    except Exception:
        return _safe_trim(_fallback_speech(material, side, round_number))
