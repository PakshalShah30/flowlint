"""One test per FlowLint rule: fires on its designated fixture, silent on the
clean fixture. Also a couple of end-to-end sanity checks on the CLI."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO_ROOT, "fixtures")
SRC = os.path.join(REPO_ROOT, "src")

sys.path.insert(0, SRC)

from flowlint.parser import parse_flow, parse_all  # noqa: E402
from flowlint.rules import (  # noqa: E402
    rule_conflicting_automation,
    rule_dead_automation,
    rule_hardcoded_id,
    rule_missing_fault_path,
    rule_recursion_risk,
)


@pytest.fixture(scope="module")
def flows():
    return parse_all(FIXTURES)


@pytest.fixture(scope="module")
def clean_flow():
    return parse_flow(os.path.join(FIXTURES, "Clean_Case_Escalation.flow-meta.xml"))


def _findings_for(findings, filename):
    return [f for f in findings if os.path.basename(f.file) == filename]


# ---------------------------------------------------------------------------
# FL001 — Missing fault path
# ---------------------------------------------------------------------------

def test_missing_fault_path_fires_on_legacy_discount_calc(flows):
    findings = rule_missing_fault_path(flows)
    hits = _findings_for(findings, "Legacy_Discount_Calc.flow-meta.xml")
    assert hits, "expected a missing-fault-path finding on Legacy_Discount_Calc"
    assert hits[0].element == "Apply_Legacy_Discount_Owner"


def test_missing_fault_path_silent_on_clean_fixture(flows, clean_flow):
    findings = rule_missing_fault_path([clean_flow])
    assert findings == []


# ---------------------------------------------------------------------------
# FL002 — Hardcoded Salesforce ID
# ---------------------------------------------------------------------------

def test_hardcoded_id_fires_on_legacy_discount_calc(flows):
    findings = rule_hardcoded_id(flows)
    hits = _findings_for(findings, "Legacy_Discount_Calc.flow-meta.xml")
    assert hits, "expected a hardcoded-ID finding on Legacy_Discount_Calc"
    assert "00658000003xy9ZAAQ" in hits[0].message


def test_hardcoded_id_silent_on_clean_fixture(flows, clean_flow):
    findings = rule_hardcoded_id([clean_flow])
    assert findings == []


# ---------------------------------------------------------------------------
# FL003 — Recursion risk
# ---------------------------------------------------------------------------

def test_recursion_risk_fires_on_lead_rating_standardizer(flows):
    findings = rule_recursion_risk(flows)
    hits = _findings_for(findings, "Lead_Rating_Standardizer.flow-meta.xml")
    assert hits, "expected a recursion-risk finding on Lead_Rating_Standardizer"
    assert hits[0].element == "Update_Lead_Rating"


def test_recursion_risk_silent_on_clean_fixture(flows, clean_flow):
    findings = rule_recursion_risk([clean_flow])
    assert findings == []


def test_recursion_risk_silent_when_entry_criteria_present(flows):
    # Opportunity_Stage_Sync also updates Lead.Rating on Update, but it has
    # entry criteria (filters), so it should NOT be flagged for recursion.
    findings = rule_recursion_risk(flows)
    hits = _findings_for(findings, "Opportunity_Stage_Sync.flow-meta.xml")
    assert hits == []


# ---------------------------------------------------------------------------
# FL004 — Dead automation
# ---------------------------------------------------------------------------

def test_dead_automation_fires_on_old_lead_router(flows):
    findings = rule_dead_automation(flows)
    hits = _findings_for(findings, "Old_Lead_Router.flow-meta.xml")
    assert hits, "expected a dead-automation finding on Old_Lead_Router"
    assert hits[0].element == "Old_Lead_Router"


def test_dead_automation_silent_on_clean_fixture(flows, clean_flow):
    # Clean_Case_Escalation is record-triggered, so it's out of scope for
    # this rule entirely (record-triggered flows are never "referenced" by
    # name — the platform invokes them automatically).
    findings = rule_dead_automation([clean_flow])
    assert findings == []


def test_dead_automation_silent_when_referenced_via_subflow(flows):
    # Legacy_Discount_Calc calls Clean_Case_Escalation as a subflow, but
    # Clean_Case_Escalation is record-triggered so it's exempt anyway; this
    # test locks in that a *referenced* flow never shows up as dead even if
    # that exemption logic changes later.
    findings = rule_dead_automation(flows)
    hits = _findings_for(findings, "Clean_Case_Escalation.flow-meta.xml")
    assert hits == []


# ---------------------------------------------------------------------------
# FL005 — Conflicting automation
# ---------------------------------------------------------------------------

def test_conflicting_automation_fires_on_both_lead_rating_flows(flows):
    findings = rule_conflicting_automation(flows)
    lead_rating_hits = _findings_for(findings, "Lead_Rating_Standardizer.flow-meta.xml")
    opp_sync_hits = _findings_for(findings, "Opportunity_Stage_Sync.flow-meta.xml")
    assert lead_rating_hits, "expected a conflict finding on Lead_Rating_Standardizer"
    assert opp_sync_hits, "expected a conflict finding on Opportunity_Stage_Sync"
    assert "Opportunity_Stage_Sync" in lead_rating_hits[0].message
    assert "Lead_Rating_Standardizer" in opp_sync_hits[0].message


def test_conflicting_automation_silent_on_clean_fixture(flows, clean_flow):
    findings = rule_conflicting_automation([clean_flow])
    assert findings == []


# ---------------------------------------------------------------------------
# End-to-end: the whole fixtures/ folder and the clean fixture in isolation
# ---------------------------------------------------------------------------

def test_clean_fixture_has_zero_findings_end_to_end():
    result = subprocess.run(
        [sys.executable, "-m", "flowlint",
         os.path.join(FIXTURES, "Clean_Case_Escalation.flow-meta.xml")],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": SRC},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "No findings" in result.stdout


def test_fixtures_folder_scan_exits_nonzero_and_reports_all_rules():
    result = subprocess.run(
        [sys.executable, "-m", "flowlint", FIXTURES],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": SRC},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    for rule_id in ("FL001", "FL002", "FL003", "FL004", "FL005"):
        assert rule_id in result.stdout, f"{rule_id} missing from full-folder scan output"
