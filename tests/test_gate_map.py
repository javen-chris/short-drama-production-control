"""The Skill-to-Gate mapping must stay in step with the protocol.

`gate_map.py` exists because nothing else in the repository mapped a Skill to a
Gate, which is why the board printed raw Skill slugs where a Gate should have
been. A hand-maintained lookup table earns its keep only if it is checked
against the thing it mirrors, so these tests read the protocol documents and
fail when the two disagree.

The authoritative sources are:

- `02_每段视频制作流程_v3.0.md`        - the G0-G8 list and their titles
- `核心自动化生产包/02_任务路由与Gate_v3.0.md` - the Gate routing table
- `skills/skill-chain.json`           - the declared Skills

These tests skip when the protocol directory is not present, so the repository
stays runnable on a machine that only has the console checked out.
"""
import json
import re
from pathlib import Path

import pytest

from production_control import gate_map
from production_control.step_audit import load_chain

PROTOCOL_ROOT = Path(r"D:\AIGC短剧本地工作流规则及协议\短剧制作核心协议")
FLOW_DOC = PROTOCOL_ROOT / "02_每段视频制作流程_v3.0.md"
ROUTING_DOC = PROTOCOL_ROOT / "核心自动化生产包" / "02_任务路由与Gate_v3.0.md"

requires_protocol = pytest.mark.skipif(
    not FLOW_DOC.is_file() and not ROUTING_DOC.is_file(),
    reason="protocol documents are not on this machine",
)


def _gate_headings(path: Path) -> dict[str, str]:
    """Gate id -> title, read from the protocol's own `## G3：资产锁定` headings."""
    if not path.is_file():
        return {}
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{2,3}\s*(G\d)[：:]\s*(.+?)\s*$", line)
        if match:
            found.setdefault(match.group(1), match.group(2))
    return found


def _routing_gates(path: Path) -> set[str]:
    """Gate ids named in the routing table's first column."""
    if not path.is_file():
        return set()
    gates: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*(G\d)\b", line)
        if match:
            gates.add(match.group(1))
    return gates


@requires_protocol
def test_every_gate_name_matches_the_protocol():
    """A Gate title the board invents is worse than no title at all."""
    headings = _gate_headings(FLOW_DOC)
    if not headings:
        pytest.skip("no Gate headings found in the flow document")
    for gate, title in headings.items():
        assert gate in gate_map.GATE_NAMES, f"{gate} exists in the protocol but not in gate_map"
        # The protocol separates clauses with `、` and adds words the board does
        # not need (`G8：剪辑、字幕、封面、发布`). Compare on the leading
        # content word rather than the whole string, so punctuation differences
        # do not read as a disagreement.
        board = re.sub(r"[、\s]", "", gate_map.GATE_NAMES[gate])
        protocol = re.sub(r"[、\s]", "", title)
        head = board[:4]
        assert head in protocol, (
            f"{gate}: board says {gate_map.GATE_NAMES[gate]!r}, protocol says {title!r}")


@requires_protocol
def test_the_board_does_not_declare_a_gate_the_protocol_never_did():
    known = set(_gate_headings(FLOW_DOC)) | _routing_gates(ROUTING_DOC)
    if not known:
        pytest.skip("no Gate list found in the protocol documents")
    unknown = set(gate_map.GATE_NAMES) - known
    assert not unknown, f"gate_map declares Gates the protocol does not: {sorted(unknown)}"


def test_every_declared_skill_maps_to_a_known_gate():
    """Totality is the property that makes the mapping useful.

    A Skill with no Gate puts a blank cell on the board, which is the exact
    defect this module was written to remove.
    """
    for row in load_chain().get("steps", []):
        skill = row["skill"]
        gates = gate_map.gates_of(skill)
        assert gates, f"{skill} is declared but has no Gate"
        for gate in gates:
            assert gate in gate_map.GATE_NAMES, f"{skill} maps to unknown Gate {gate}"


def test_every_declared_skill_has_a_chinese_label():
    for row in load_chain().get("steps", []):
        skill = row["skill"]
        label = gate_map.skill_label(skill)
        assert label and label != skill, f"{skill} would show as a raw slug"


def test_the_two_qa_rounds_are_distinguishable():
    """Pre- and post-generation QA share a Skill id but are different events.

    Showing both as `G5/G7 独立 QA` with no qualifier would hide which round ran.
    """
    assert gate_map.qa_mode_label(["pre_generation"]) == "生成前 QA"
    assert gate_map.qa_mode_label(["post_generation"]) == "成片 QA"
    assert "生成前 QA" in gate_map.annotated_gate("short-drama-production-qa", ["pre_generation"])
    assert "成片 QA" in gate_map.annotated_gate("short-drama-production-qa", ["post_generation"])


def test_provider_adapters_are_marked_as_alternatives():
    """Three adapters are one choice, not three obligations.

    A run owes exactly one submission; listing the other two as `未做` is
    technically true and completely misleading.
    """
    adapters = ["runninghub-local-adapter", "xiaoyunque-local-adapter", "libtv-local-adapter"]
    assert all(gate_map.is_alternative(a) for a in adapters)
    assert all(gate_map.gates_of(a) == ("G6",) for a in adapters)
    assert not gate_map.is_alternative("short-drama-production-qa")


def test_the_mapping_is_a_declared_module_not_a_side_effect():
    """`gate_map` is import-only: no I/O, no state, safe to call from any renderer."""
    assert isinstance(gate_map.GATE_NAMES, dict)
    assert isinstance(gate_map.GATE_OF_SKILL, dict)
    assert isinstance(gate_map.SKILL_NAMES, dict)


def test_skill_chain_gates_are_all_in_protocol_order():
    """Gates the chain touches must appear in ascending protocol order.

    The chain is the execution order; if a Gate appears out of order the chain
    and the Gate list disagree about what "next" means.

    The two QA rounds are what make this non-trivial: pre-generation QA is a G5
    gate and post-generation QA is the G7 gate, so the Gate for a QA step has to
    come from its mode. Mapping the Skill to a fixed (G5, G7) pair would render
    the chain as G5 -> G7 -> G6.
    """
    seen: list[str] = []
    for row in load_chain().get("steps", []):
        modes = [row["mode"]] if row.get("mode") else []
        for gate in gate_map.gates_for(row["skill"], modes):
            if not seen or seen[-1] != gate:
                seen.append(gate)
    order = list(gate_map.GATE_NAMES)
    indexes = [order.index(g) for g in seen if g in order]
    assert indexes == sorted(indexes), f"Gates out of order: {seen}"


def test_a_qa_step_takes_its_gate_from_its_round():
    """Without the mode, QA resolves to the pair and the order breaks again."""
    assert gate_map.gates_for("short-drama-production-qa", ["pre_generation"]) == ("G5",)
    assert gate_map.gates_for("short-drama-production-qa", ["post_generation"]) == ("G7",)
    # With no mode recorded, both Gates are shown rather than a guess.
    assert gate_map.gates_for("short-drama-production-qa") == ("G5", "G7")
    # A non-QA step ignores modes entirely.
    assert gate_map.gates_for("short-drama-image-generator", ["pre_generation"]) == ("G3",)
