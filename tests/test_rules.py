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


def _write_flow(directory, api_name, body, status="Active", process_type="AutoLaunchedFlow"):
    path = directory / f"{api_name}.flow-meta.xml"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Flow xmlns="http://soap.sforce.com/2006/04/metadata">'
        f"<label>{api_name}</label><processType>{process_type}</processType>"
        f"<status>{status}</status>{body}</Flow>",
        encoding="utf-8",
    )
    return str(path)


def _record_triggered_rating_writer(trigger_type):
    return (
        "<recordUpdates><name>Set_Rating</name><inputReference>$Record</inputReference>"
        "<inputAssignments><field>Rating</field><value><stringValue>Hot</stringValue></value>"
        "</inputAssignments><faultConnector><targetReference>X</targetReference></faultConnector>"
        "</recordUpdates>"
        "<start><object>Lead</object>"
        f"<recordTriggerType>{trigger_type}</recordTriggerType>"
        "<triggerType>RecordAfterSave</triggerType>"
        "<filters><field>Rating</field><operator>NotEqualTo</operator>"
        "<value><stringValue>Hot</stringValue></value></filters></start>"
    )


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


def test_dead_automation_ignores_name_embedded_in_longer_identifier(tmp_path):
    # 'Router' appearing inside 'Old_Lead_Router' is not a reference to Router.
    _write_flow(tmp_path, "Router", "")
    _write_flow(
        tmp_path,
        "Caller",
        "<subflows><name>Call_It</name><flowName>Old_Lead_Router</flowName></subflows>",
        status="Draft",
    )
    findings = rule_dead_automation(parse_all(str(tmp_path)))
    assert [f.element for f in findings] == ["Router"]


def test_dead_automation_silent_when_referenced_by_exact_name(tmp_path):
    _write_flow(tmp_path, "Router", "")
    _write_flow(
        tmp_path,
        "Caller",
        "<subflows><name>Call_It</name><flowName>Router</flowName></subflows>",
        status="Draft",
    )
    assert rule_dead_automation(parse_all(str(tmp_path))) == []


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


def test_conflicting_automation_fires_across_update_and_create_and_update(tmp_path):
    _write_flow(tmp_path, "On_Update", _record_triggered_rating_writer("Update"))
    _write_flow(tmp_path, "On_Save", _record_triggered_rating_writer("CreateAndUpdate"))
    findings = rule_conflicting_automation(parse_all(str(tmp_path)))
    assert len(findings) == 2
    assert all("Lead.Rating on Update," in f.message for f in findings)


def test_conflicting_automation_reports_each_writer_once_across_events(tmp_path):
    _write_flow(tmp_path, "Save_A", _record_triggered_rating_writer("CreateAndUpdate"))
    _write_flow(tmp_path, "Save_B", _record_triggered_rating_writer("CreateAndUpdate"))
    findings = rule_conflicting_automation(parse_all(str(tmp_path)))
    assert len(findings) == 2
    assert all("on Create and Update," in f.message for f in findings)


def test_conflicting_automation_silent_for_create_vs_update(tmp_path):
    _write_flow(tmp_path, "On_Create", _record_triggered_rating_writer("Create"))
    _write_flow(tmp_path, "On_Update", _record_triggered_rating_writer("Update"))
    assert rule_conflicting_automation(parse_all(str(tmp_path))) == []


def test_non_utf8_file_reports_its_path(tmp_path):
    bad = tmp_path / "Bad.flow-meta.xml"
    bad.write_bytes(b"\xff\xfe<bad")
    with pytest.raises(ValueError, match="Bad.flow-meta.xml"):
        parse_all(str(tmp_path))


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
