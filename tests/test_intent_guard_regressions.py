"""Guards must not turn real document questions into unrelated index reports."""
from __future__ import annotations

from types import SimpleNamespace

from document_agent.agent import _indexed_inventory_answer
from document_agent.db import connect
from document_agent.guardrails import exact_item_answer, exact_register_milestone_answer
from document_agent.structured_reporting import (
    contrasted_internal_and_contractual_dates,
)


def test_required_acceptance_document_is_not_an_index_inventory():
    conn = connect(":memory:")
    try:
        question = ("Do the latest quality inspections alone prove final "
                    "contractual handover? What document is still required?")
        trace = [{"name": "list_documents", "ok": True}]
        assert _indexed_inventory_answer(conn, question, trace) is None
        assert _indexed_inventory_answer(
            conn, "What document is still required for approval?", trace,
        ) is None
        actual = _indexed_inventory_answer(
            conn, "Which documents are indexed?", trace,
        )
        assert actual is not None
        assert "Indexed files:" in actual.text
    finally:
        conn.close()


def test_signed_addendum_work_is_not_an_unknown_milestone():
    conn = connect(":memory:")
    try:
        plan = SimpleNamespace(scope_kind="all_indexed", document_scope=[])
        question = ("What extra physical work was approved by signed "
                    "Addendum A-06 and what was its approved cost?")
        assert exact_register_milestone_answer(conn, question, plan) is None
    finally:
        conn.close()


def test_three_way_schedule_request_not_handled_by_two_date_calculator():
    conn = connect(":memory:")
    try:
        plan = SimpleNamespace(scope_kind="all_indexed", document_scope=[])
        question = ("Contrast internal readiness with the original contractual "
                    "handover date and the later proposal, stating their statuses.")
        assert contrasted_internal_and_contractual_dates(
            conn, question, plan,
        ) is None
    finally:
        conn.close()


def test_signed_addendum_cost_not_misrouted_to_exact_boq_item():
    conn = connect(":memory:")
    try:
        plan = SimpleNamespace(scope_kind="all_indexed", document_scope=[])
        question = ("What extra physical work was approved by signed "
                    "Addendum A-06 and what was its approved cost?")
        assert exact_item_answer(conn, question, plan) is None
        assert exact_item_answer(
            conn, "What was the cost of signed Amendment A-06?", plan,
        ) is None
    finally:
        conn.close()
