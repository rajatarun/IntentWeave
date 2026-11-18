import sys
from pathlib import Path

from intentweave.observatory import emit_intent_label_metric

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contracts.conformance import check_item, load_contract  # noqa: E402


def test_observatory_item_conforms():
    item = emit_intent_label_metric(
        trace_id="trace-test",
        label="question",
        source="heuristic",
        confidence=0.8,
        model="gemini-decision-1",
    )
    assert item is not None
    problems = check_item(item, load_contract())
    assert problems == [], problems
