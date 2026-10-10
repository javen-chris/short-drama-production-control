"""The step registry: one key, many spellings, no silent mis-joins.

The failure this module exists to end: the same twelve step names used to be
written out in four unrelated places, and every command the producing model ran
typed one of them by hand. One wrong letter anywhere and the event was stored
under a name nothing else recognised - recorded, and invisible. Three incidents
in a single day came from that.

So the tests here are about *tolerance on input* and *strictness on output*:
accept every reasonable spelling, canonicalise it, and refuse what cannot be
placed rather than storing it under a name nobody can match.
"""
import json
import re
from pathlib import Path

import pytest

from production_control import step_registry


# --- The registry itself ------------------------------------------------------

def test_every_declared_step_carries_a_stable_id():
    steps = step_registry.declared()
    assert len(steps) >= 12
    ids = [s.id for s in steps]
    assert all(ids), "every step needs an id, it is the join key"
    assert len(set(ids)) == len(ids), "ids must be unique"


def test_the_registry_is_the_only_copy_of_the_skill_names():
    """gate_map and run_compliance must not keep their own lists any more."""
    from production_control import gate_map
    from production_control.run_compliance import STEP_PROTOCOL_REQUIREMENTS

    declared = {s.skill for s in step_registry.declared()}
    assert set(gate_map.GATE_OF_SKILL) == declared
    assert declared <= set(STEP_PROTOCOL_REQUIREMENTS)


def test_the_gate_of_every_step_comes_from_the_registry():
    from production_control import gate_map

    for step in step_registry.declared():
        assert step.gate, f"{step.skill} declares no Gate"
        # A skill may back two entries with different Gates - the two QA rounds
        # share one skill - so gate_map reports the union and each entry must be
        # a subset of it.
        assert set(step.gate) <= set(gate_map.gates_of(step.skill)), step.id


def test_markers_are_recognised_but_not_part_of_the_chain():
    marker_names = {s.skill for s in step_registry.load() if s.marker}
    assert "protocol-attestation" in marker_names
    assert not marker_names & {s.skill for s in step_registry.declared()}


# --- Input tolerance ----------------------------------------------------------

@pytest.mark.parametrize("typed, expected", [
    ("S08", "short-drama-prompt-compiler"),
    ("s08", "short-drama-prompt-compiler"),
    ("s8", "short-drama-prompt-compiler"),
    ("short-drama-prompt-compiler", "short-drama-prompt-compiler"),
    ("Short_Drama_Prompt-Compiler", "short-drama-prompt-compiler"),
    ("short drama prompt compiler", "short-drama-prompt-compiler"),
    ("  short-drama-prompt-compiler  ", "short-drama-prompt-compiler"),
    ("prompt-compiler", "short-drama-prompt-compiler"),
    ("libtv", "libtv-local-adapter"),
    ("S12", "short-drama-task-monitor"),
    ("runninghub", "runninghub-local-adapter"),
    ("protocol-attestation", "protocol-attestation"),
])
def test_a_known_spelling_resolves_to_the_declared_skill(typed, expected):
    outcome = step_registry.resolve(typed)
    assert outcome.ok, f"{typed} should resolve"
    assert outcome.step.skill == expected


@pytest.mark.parametrize("typed, expected", [
    ("short-drama-prompt-compilor", "short-drama-prompt-compiler"),    # one letter short
    ("short-drama-prompt-compilerx", "short-drama-prompt-compiler"),   # one letter extra
    ("short-dram-prompt-compiler", "short-drama-prompt-compiler"),     # one letter missing
])
def test_a_one_letter_slip_is_corrected_rather_than_lost(typed, expected):
    """A typo must not cost a day of work, but it must not be silent either."""
    outcome = step_registry.resolve(typed)
    assert outcome.ok, f"{typed} should still be recognised"
    assert outcome.step.skill == expected
    assert outcome.matched_by == "fuzzy"
    assert not outcome.exact, "a guessed match has to announce itself"


def test_dropping_the_hyphens_is_an_exact_match_not_a_guess():
    """Folding is deterministic, so it does not need to be flagged as a guess."""
    outcome = step_registry.resolve("libtvlocaladapter")
    assert outcome.ok
    assert outcome.step.skill == "libtv-local-adapter"
    assert outcome.matched_by == "normalised"
    assert outcome.exact


@pytest.mark.parametrize("invented", [
    "g6-reference-integrity",
    "g6-seedance25-preflight",
    "independent-qa-route-fix",
    "g3-asset-audit",
    "G2-shot-confirm",
])
def test_an_invented_name_is_refused_not_stored(invented):
    """This is the case that produced a frozen board for a whole afternoon."""
    outcome = step_registry.resolve(invented)
    assert not outcome.ok, f"{invented} is not a declared step and must not resolve"


def test_an_empty_name_resolves_to_nothing():
    for blank in ("", "   ", "\t"):
        assert not step_registry.resolve(blank).ok


def test_a_refusal_offers_the_closest_candidates():
    outcome = step_registry.resolve("short-drama-prompt-compil")
    if not outcome.ok:
        assert outcome.suggestions
        assert any(s.skill == "short-drama-prompt-compiler" for s in outcome.suggestions)


def test_the_choice_list_names_every_step_with_its_id():
    text = step_registry.format_choices()
    for step in step_registry.declared():
        assert step.id in text
        assert step.skill in text


# --- The registry file is the contract ---------------------------------------

def test_a_broken_registry_degrades_instead_of_crashing(tmp_path):
    broken = tmp_path / "skill-chain.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert step_registry.load(broken) == ()
    assert not step_registry.resolve("S01", broken).ok


def test_an_empty_registry_degrades_instead_of_crashing(tmp_path):
    empty = tmp_path / "skill-chain.json"
    empty.write_text(json.dumps({"steps": []}), encoding="utf-8")
    assert step_registry.load(empty) == ()


# --- Guard against the copies coming back ------------------------------------
# The twelve names used to be written out in four modules and every command the
# producing model typed. Each copy was a place the list could disagree with
# itself, and a disagreement is a silent mis-join. This test fails the build if
# a module starts carrying its own list again.

def _skill_name_literals(path):
    """String constants that exactly equal a declared skill name.

    Docstrings and comments are ignored on purpose: prose may mention a step by
    name, code may not depend on the spelling.
    """
    import ast

    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    declared = {s.skill for s in step_registry.load()}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docstrings:
                continue
            if node.value.strip() in declared:
                found.add(node.value.strip())
    return found


@pytest.mark.parametrize("module", [
    "gate_map.py",
    "run_compliance.py",
    "orchestrator.py",
    "skill_chain_validator.py",
    "step_audit.py",
    "progress.py",
    "run_report.py",
    "run_index.py",
    "run_server.py",
])
def test_no_module_keeps_its_own_copy_of_the_skill_names(module):
    root = step_registry.repo_root() / "src" / "production_control" / module
    offenders = _skill_name_literals(root)
    assert not offenders, (
        f"{module} hardcodes step names {sorted(offenders)}; "
        "read them from step_registry instead"
    )


# --- Prose cannot drift either ------------------------------------------------
# Documents that name the steps are read by people and copied into prompts, so a
# stale name in one of them is just as costly as a stale name in code - it is how
# the agent learns to type something the board cannot place. The check is that
# any step-shaped token in these files is a step the registry knows about.

#: Files whose step references must stay true.
DOCS = ("docs/protocol-mapping.md", "看板上报提示词.md")

#: Anything shaped like a step id or a skill slug.
_STEP_TOKEN = re.compile(r"\b(S\d{2}|[a-z][a-z0-9]*(?:-[a-z0-9]+){2,})\b")


@pytest.mark.parametrize("doc", DOCS)
def test_the_docs_only_name_steps_the_registry_declares(doc):
    root = step_registry.repo_root() / doc
    if not root.is_file():
        pytest.skip(f"{doc} not present")

    # Slugs that look like step names but are deliberately something else.
    allowed = {"skills-local", "append-event"}
    known_ids = {s.id for s in step_registry.load()} | {
        s.display_id.rsplit("-", 1)[-1] for s in step_registry.load() if s.display_id
    }
    known_skills = {s.skill for s in step_registry.load()}
    known_aliases = {a for s in step_registry.load() for a in s.aliases}

    text = Path(root).read_text(encoding="utf-8")
    for step_id in re.findall(r"\bS\d{2}\b", text):
        assert step_id in known_ids, f"{doc} names {step_id}, which is not a declared step"
    for slug in re.findall(r"\bshort-drama-[a-z-]+|\b[a-z]+-local-adapter\b", text):
        if slug in allowed or slug in known_aliases:
            continue
        assert slug in known_skills, (
            f"{doc} names {slug}, which the registry does not declare"
        )
