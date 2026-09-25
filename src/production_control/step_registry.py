"""The one place that turns whatever someone typed into a canonical step.

Why this module exists
----------------------
Until now the same twelve step names were written out in four unrelated places
(the chain, the Gate map, the protocol-requirement table, and every command the
producing model typed by hand). A single missing letter anywhere broke the join
silently: the event was written, the board could not place it, and the work
looked like it had never happened. Three separate incidents in one day came from
that one design choice.

Names are for people. Machines need a key that cannot drift, so:

* `id`      - the join key. `S01`..`S12`. Short, stable, never renamed.
* `skill`   - the executor, kept for display and for the tooling that spawns it.
* `name_zh` - what a person reads.
* `aliases` - short forms a model is likely to type instead.

`resolve()` accepts any of those, plus case/hyphen/underscore variations, plus a
near-miss spelling, and returns the canonical step. Callers stop comparing
strings and start asking this module. When nothing matches it says so, and
suggests the closest candidates, instead of inventing a step.

The registry is `skills/skill-chain.json` - the same file the orchestrator reads
for ordering, so there is exactly one list to maintain.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

#: Where the registry lives, relative to the repository root.
CHAIN_RELPATH = "skills/skill-chain.json"

#: A near-miss at or above this similarity is treated as the intended step. It
#: has to be forgiving enough to survive a typo in a 28-character name (which
#: costs about 0.04 of similarity) and strict enough that `-reference-nodes`
#: does not become some unrelated adapter.
FUZZY_ACCEPT = 0.88

#: Below the accept threshold but above this, a candidate is worth *showing* to
#: the caller as a suggestion. Never applied automatically - a wrong step name
#: attributed silently is worse than a refused one.
FUZZY_SUGGEST = 0.62


@dataclass(frozen=True)
class Step:
    """One declared step. `id` is the key; everything else is a label."""

    id: str
    skill: str
    name_zh: str = ""
    gate: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    protocol_refs: tuple[str, ...] = ()
    #: The prompt shown when this step needs a human decision before the run may
    #: cross it. Empty means the step does not stop for one.
    approval: str = ""
    marker: bool = False

    def as_dict(self) -> dict:
        return {
            "id": self.id, "skill": self.skill, "name_zh": self.name_zh,
            "gate": list(self.gate), "aliases": list(self.aliases),
            "approval": self.approval, "marker": self.marker,
        }


@dataclass(frozen=True)
class Resolution:
    """What `resolve()` concluded, and how confident it is."""

    step: Step | None
    matched_by: str = ""          # id / skill / alias / normalised / fuzzy
    query: str = ""
    score: float = 0.0
    suggestions: tuple[Step, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.step is not None

    @property
    def exact(self) -> bool:
        """True when no guessing was involved."""
        return self.matched_by in {"id", "skill", "alias", "normalised"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalise(text: str) -> str:
    """Fold away everything that differs between two spellings of one name.

    Case, hyphens, underscores, spaces and full-width punctuation all go. This is
    what makes `Short_Drama_Prompt-Compiler` and `short drama prompt compiler`
    the same step without anyone having to agree on a convention.
    """
    folded = unicodedata.normalize("NFKC", text or "").strip().lower()
    return re.sub(r"[\s\-_.·、，,／/\\]+", "", folded)


def _collapse_id(text: str) -> str:
    """`s1` and `S01` are the same id; so are `m1` and `M01`."""
    match = re.fullmatch(r"([a-z]+)0*(\d+)", _normalise(text))
    if not match:
        return ""
    return f"{match.group(1)}{int(match.group(2)):02d}".upper()


def load(path: str | Path | None = None) -> tuple[Step, ...]:
    """Every declared step, in chain order. Markers come last.

    A missing or unreadable registry returns an empty tuple rather than raising:
    the board must still render a project whose console install is incomplete.
    """
    target = Path(path) if path else repo_root() / CHAIN_RELPATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    steps: list[Step] = []
    for entry in data.get("steps", []) or []:
        skill = (entry.get("skill") or "").strip()
        if not skill:
            continue
        steps.append(Step(
            id=(entry.get("id") or "").strip().upper(),
            skill=skill,
            name_zh=entry.get("name_zh", ""),
            gate=tuple(entry.get("gate", []) or []),
            aliases=tuple(entry.get("aliases", []) or []),
            protocol_refs=tuple(entry.get("protocol_refs", []) or []),
            approval=entry.get("approval", ""),
        ))
    for entry in data.get("markers", []) or []:
        skill = (entry.get("skill") or "").strip()
        if not skill:
            continue
        steps.append(Step(
            id=(entry.get("id") or "").strip().upper(),
            skill=skill,
            name_zh=entry.get("name_zh", ""),
            aliases=tuple(entry.get("aliases", []) or []),
            marker=True,
        ))
    return tuple(steps)


def declared(path: str | Path | None = None) -> tuple[Step, ...]:
    """Only the real chain steps - the ones a run's progress is measured on."""
    return tuple(s for s in load(path) if not s.marker)


def by_skill(skill: str, path: str | Path | None = None) -> Step | None:
    for step in load(path):
        if step.skill == skill:
            return step
    return None


def by_id(step_id: str, path: str | Path | None = None) -> Step | None:
    want = _collapse_id(step_id)
    if not want:
        return None
    for step in load(path):
        if step.id == want:
            return step
    return None


def _keys(step: Step) -> list[tuple[str, str]]:
    """The literal spellings this step answers to, best first."""
    pairs = [("id", step.id), ("skill", step.skill)]
    pairs += [("alias", a) for a in step.aliases]
    return [(kind, text) for kind, text in pairs if text]


def resolve(text: str, path: str | Path | None = None) -> Resolution:
    """Turn typed text into a declared step, or explain why it cannot be.

    The order is deliberate: exact matches first, then folding, then a forgiving
    near-miss. Only the near-miss tier guesses, and it announces itself through
    `matched_by == "fuzzy"` so the caller can warn rather than stay silent.
    """
    query = (text or "").strip()
    steps = load(path)
    if not query or not steps:
        return Resolution(step=None, query=query)

    lowered = unicodedata.normalize("NFKC", query).strip().lower()

    for step in steps:
        for kind, literal in _keys(step):
            if literal.lower() == lowered:
                return Resolution(step=step, matched_by=kind, query=query, score=1.0)

    folded_wanted = _normalise(query)
    collapsed_wanted = _collapse_id(query)
    for step in steps:
        if collapsed_wanted and step.id == collapsed_wanted:
            return Resolution(step=step, matched_by="id", query=query, score=1.0)
        for kind, literal in _keys(step):
            if _normalise(literal) == folded_wanted:
                return Resolution(step=step, matched_by="normalised", query=query, score=1.0)

    scored: list[tuple[float, Step]] = []
    for step in steps:
        best = 0.0
        for _, literal in _keys(step):
            best = max(best, SequenceMatcher(None, folded_wanted, _normalise(literal)).ratio())
        scored.append((best, step))
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))

    if scored and scored[0][0] >= FUZZY_ACCEPT:
        score, step = scored[0]
        return Resolution(step=step, matched_by="fuzzy", query=query, score=score)

    near = tuple(step for score, step in scored[:3] if score >= FUZZY_SUGGEST)
    return Resolution(step=None, query=query, suggestions=near)


def qa_steps(path: str | Path | None = None) -> tuple[Step, ...]:
    """The steps the chain marks as a review round.

    A QA step is identified by carrying a QA `mode`, not by its name, so renaming
    the Skill cannot quietly turn a review into an ordinary step.
    """
    qa_modes = {"pre_generation", "post_generation"}
    target = Path(path) if path else repo_root() / CHAIN_RELPATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    wanted = {
        entry.get("skill", "")
        for entry in (data.get("steps", []) or [])
        if entry.get("mode") in qa_modes
    }
    return tuple(s for s in load(path) if s.skill in wanted)


def approval_breakpoints(path: str | Path | None = None) -> dict[str, str]:
    """Steps that need a human decision before the run may cross them.

    Derived from the registry's `approval` field so the prompt text lives beside
    the step it belongs to, instead of in a second name-keyed table that has to
    be kept in sync by hand.
    """
    return {s.skill: s.approval for s in load(path) if s.approval}


def describe(step: Step) -> str:
    """A one-line label for a step: `S08 · 视频 Prompt 编译`."""
    return f"{step.id} · {step.name_zh or step.skill}" if step else ""


def format_choices(path: str | Path | None = None, *, width: int = 78) -> str:
    """The step table, for a refusal message or a client that asked for it.

    Every spelling is listed in the order it is accepted - the id first, because
    it is the shortest and the only one that cannot drift. This is what makes a
    refusal actionable rather than merely obstructive: the caller can copy the
    next command straight out of the error.
    """
    lines: list[str] = []
    for step in load(path):
        where = "标记" if step.marker else ("/".join(step.gate) or "-")
        alias = (" / ".join(step.aliases[:3]))[:34]
        head = (f"  {step.id:<4} {where:<7} {step.skill:<32} "
                f"{step.name_zh or '-'}")
        lines.append(head[:width])
        if alias:
            lines.append(f"       alias: {alias}")
        if step.protocol_refs:
            lines.append(f"       必修: {'、'.join(step.protocol_refs)}"[:width + 20])
    return "\n".join(lines)


def format_ids(path: str | Path | None = None) -> str:
    """Just `S01=skill` pairs on one line, for a compact prompt or tooltip."""
    return "  ".join(f"{s.id}={s.skill}" for s in load(path))
