"""The one place that answers: which Gate does this Skill belong to?

`skills/skill-chain.json` declares *executors* - the twelve Skills that run in
order. It says nothing about Gates, so every UI that wanted to show "which step
of the protocol is this" had nothing to read and fell back to printing the raw
Skill slug. That is why the board showed a column of
`short-drama-production-router` with an empty Gate column next to it: the
mapping did not exist anywhere in the repository.

The authoritative Gate list is `02_每段视频制作流程_v3.0.md` (G0-G8) and the
routing table in `核心自动化生产包/02_任务路由与Gate_v3.0.md`. This module is the
projection of that list onto the Skill chain - a lookup table, not a new rule.

Gate letters are stable protocol vocabulary: a board that shows "G3 资产锁定"
tells the user something; a board that shows `short-drama-asset-router` does not.
So the Gate is the primary label everywhere and the Skill name is the secondary
detail, never the other way round.
"""
from __future__ import annotations

import json

from . import step_registry


def _registry_entries() -> list[dict]:
    """The raw chain entries, for the few fields that are not on `Step`.

    `Step` deliberately carries only what a human reads plus the protocol refs.
    Provider and alternative-group metadata stays in the JSON, so it is read
    here on demand rather than duplicated into a table in this file.
    """
    path = step_registry.repo_root() / step_registry.CHAIN_RELPATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(data.get("steps", []) or [])


#: Canonical Gate names, in protocol order. G0-G8 from `02_每段视频制作流程_v3.0.md`.
GATE_NAMES = {
    "G0": "接入与连续性核对",
    "G1": "秒表脚本",
    "G2": "镜头确认",
    "G3": "资产锁定",
    "G4": "故事本确认",
    "G5": "视频 Prompt 确认",
    "G6": "生成",
    "G7": "独立视频 QA 与用户审片",
    "G8": "剪辑、字幕、封面、发布",
}

#: Which Gate each declared Skill serves, and its Chinese name - both read from
#: `skills/skill-chain.json` through `step_registry`, so this module holds no
#: second copy of the twelve names. The duplicate tables that used to live here
#: were one of four places the same list existed, and every divergence between
#: them was a silent mis-join on the board.
#:
#: `short-drama-production-qa` is the exception: it appears twice in the chain,
#: as pre-generation QA (a G5 gate) and post-generation QA (the G7 gate). A
#: single fixed Gate would put a G7 row before G6 and make the protocol read
#: out of order, so its Gate comes from the chain's own `mode` - see
#: `gate_badge` / `annotated_gate`.
def _gates_of_skill() -> dict[str, tuple[str, ...]]:
    mapping: dict[str, tuple[str, ...]] = {}
    for step in step_registry.declared():
        mapping.setdefault(step.skill, step.gate)
    return mapping


def _names_of_skill() -> dict[str, str]:
    return {step.skill: step.name_zh for step in step_registry.load() if step.name_zh}


GATE_OF_SKILL = _gates_of_skill()
SKILL_NAMES = _names_of_skill()

#: A QA Skill's real Gate depends on which round it is. Pre-generation QA signs
#: off the Prompt, so it belongs to G5; post-generation QA signs off the video,
#: so it belongs to G7. Without this the chain would read G5 -> G7 -> G6.
GATE_OF_QA_MODE = {
    "pre_generation": "G5",
    "post_generation": "G7",
}

#: Skills whose Gate depends on `mode` rather than being fixed: exactly those the
#: registry declares with a QA `mode`, so this set cannot drift from the chain.
def _qa_skills() -> frozenset[str]:
    return frozenset(
        entry.get("skill", "") for entry in _registry_entries()
        if entry.get("mode") in GATE_OF_QA_MODE
    )


QA_SKILLS = _qa_skills()

#: The Chinese name of each Skill, so the board never shows a bare slug. Read
#: from the registry above; `skill_label` falls back to the id for a step the
#: registry has never heard of, because a project may legitimately record a
#: custom step and an unknown name must show as itself, not as a crash.

#: Two QA rounds exist and they are not the same event. `pre_generation` runs
#: before anything is submitted; `post_generation` runs on the finished video.
QA_MODE_LABELS = {
    "pre_generation": "生成前 QA",
    "post_generation": "成片 QA",
}

#: Provider adapters are alternatives, not a sequence. Showing them as three
#: consecutive "未做" rows implies the run owes three submissions; it owes one.
ALTERNATIVE_GROUP_LABEL = "三选一（本次只用其中一个平台）"


def gate_label(skill: str, modes: list[str] | tuple[str, ...] | None = None) -> str:
    """`G3 资产锁定` - the Gate letter is the key, the name is for humans."""
    gates = gates_for(skill, modes)
    if not gates:
        return ""
    return " / ".join(f"{g} {GATE_NAMES.get(g, '')}".strip() for g in gates)


def gates_of(skill: str) -> tuple[str, ...]:
    """Every Gate this Skill can serve, ignoring which round it is."""
    return GATE_OF_SKILL.get(skill, ())


def gates_for(skill: str, modes: list[str] | tuple[str, ...] | None = None) -> tuple[str, ...]:
    """The Gate(s) this particular occurrence of the Skill serves.

    Only a QA step resolves its Gate from `mode`: pre-generation QA is the G5
    gate, post-generation QA is the G7 gate. For every other Skill `mode` is
    ignored - the chain uses the field for other things too, and reading it
    unconditionally would relabel unrelated steps.
    """
    if modes and skill in QA_SKILLS:
        resolved = [GATE_OF_QA_MODE[m] for m in modes if m in GATE_OF_QA_MODE]
        if resolved:
            return tuple(dict.fromkeys(resolved))
    return gates_of(skill)


def gate_badge(skill: str, modes: list[str] | tuple[str, ...] | None = None) -> str:
    """Just the letters, for a compact column: `G3`."""
    gates = gates_for(skill, modes)
    return " / ".join(gates) if gates else ""


def skill_label(skill: str) -> str:
    """The Chinese name of a Skill, falling back to the id.

    Falling back rather than raising matters: a project may legitimately record a
    custom step the console has never heard of, and an unknown name must show as
    itself, not as a crash.
    """
    return SKILL_NAMES.get(skill, skill)


def is_alternative(skill: str) -> bool:
    """True for provider adapters, which are mutually exclusive in one run.

    Read from the registry's `alternative_group` rather than a name list, so
    adding a fourth provider does not need an edit here.
    """
    return alternative_group(skill) != ""


def alternative_group(skill: str) -> str:
    """The mutual-exclusion group a step belongs to, or "" if it stands alone."""
    for entry in _registry_entries():
        if entry.get("skill") == skill and entry.get("alternative_group"):
            return entry["alternative_group"]
    return ""


def qa_mode_label(modes: list[str] | tuple[str, ...] | None) -> str:
    if not modes:
        return ""
    return " / ".join(QA_MODE_LABELS.get(m, m) for m in modes)


def annotated_gate(skill: str, modes: list[str] | tuple[str, ...] | None = None) -> str:
    """Gate plus the QA-round qualifier, so the two QA rows are distinguishable."""
    base = gate_label(skill, modes)
    extra = qa_mode_label(modes)
    if extra:
        return f"{base}（{extra}）" if base else extra
    return base
