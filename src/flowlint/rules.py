"""The five FlowLint rules.

Each rule is a function ``(flows: list[Flow]) -> list[Finding]``. Rules that
only need to reason about a single file still receive the full list because
some checks (dead automation, conflicting automation) are inherently
cross-file. Keeping one signature makes the rule registry in `RULES` simple.
"""

from __future__ import annotations

import re

from .models import DML_KINDS, DML_LABELS, Finding, Flow

# ---------------------------------------------------------------------------
# Rule metadata (used by --rules and the report)
# ---------------------------------------------------------------------------

RULE_DESCRIPTIONS = {
    "FL001": "Missing fault path on a DML / Get Records element",
    "FL002": "Hardcoded Salesforce record ID",
    "FL003": "Recursion risk: record-triggered flow updates its own trigger record with no entry criteria",
    "FL004": "Dead automation: Active flow that is never referenced anywhere in the scanned folder",
    "FL005": "Conflicting automation: two+ Active flows on the same object/trigger write the same field",
}

RECORD_TRIGGER_UPDATE_TYPES = {"Update", "CreateAndUpdate"}


# ---------------------------------------------------------------------------
# FL001 — Missing fault path
# ---------------------------------------------------------------------------

def rule_missing_fault_path(flows: list[Flow]) -> list[Finding]:
    findings = []
    for flow in flows:
        for elem in flow.dml_elements:
            if elem.has_fault_connector:
                continue
            findings.append(
                Finding(
                    rule_id="FL001",
                    severity="error",
                    file=flow.path,
                    element=elem.name,
                    message=(
                        f"'{elem.name}' ({DML_LABELS[elem.kind]}) has no faultConnector. "
                        "If this operation fails at runtime (validation rule, trigger, "
                        "storage limit, lock contention...) the flow will fail silently "
                        "or surface a raw error to the end user."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# FL002 — Hardcoded Salesforce ID
# ---------------------------------------------------------------------------

# 15 or 18 contiguous alphanumerics, not glued to more alnum/underscore on
# either side (so we don't split "Update_Lead_Rating_18charsXYZ..." wrong, and
# don't match inside a longer identifier).
_ID_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z0-9]{15}|[A-Za-z0-9]{18})(?![A-Za-z0-9_])")


def _looks_like_salesforce_id(candidate: str) -> bool:
    """Heuristic to avoid false positives on ordinary English words/identifiers.

    A real Salesforce ID always mixes letters and digits, and in practice
    mixes upper- and lower-case letters (base62 encoding of the record's
    internal number + a checksum). Plain words like "RecordAfterSave" or
    "AutoLaunchedFlow" contain no digits at all and are filtered out here.
    """
    has_digit = any(c.isdigit() for c in candidate)
    has_lower = any(c.islower() for c in candidate)
    has_upper = any(c.isupper() for c in candidate)
    return has_digit and has_lower and has_upper


def rule_hardcoded_id(flows: list[Flow]) -> list[Finding]:
    findings = []
    for flow in flows:
        for node in flow.named_nodes:
            seen_in_node = set()
            for match in _ID_CANDIDATE_RE.finditer(node.raw_xml):
                candidate = match.group(1)
                if not _looks_like_salesforce_id(candidate):
                    continue
                if candidate in seen_in_node:
                    continue
                seen_in_node.add(candidate)
                findings.append(
                    Finding(
                        rule_id="FL002",
                        severity="error",
                        file=flow.path,
                        element=node.name,
                        message=(
                            f"'{node.name}' contains a hardcoded record ID literal "
                            f"('{candidate}'). Record IDs differ between sandboxes, "
                            "orgs, and production — hardcoding one will break the "
                            "flow the moment it's deployed anywhere else. Use a "
                            "Get Records / Custom Metadata / Custom Label lookup instead."
                        ),
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# FL003 — Recursion risk
# ---------------------------------------------------------------------------

def rule_recursion_risk(flows: list[Flow]) -> list[Finding]:
    findings = []
    for flow in flows:
        start = flow.start
        if start.record_trigger_type not in RECORD_TRIGGER_UPDATE_TYPES:
            continue
        if start.has_filters:
            continue  # entry criteria present -> not every save re-enters
        self_updates = [
            e
            for e in flow.dml_elements
            if e.kind == "recordUpdates" and e.input_reference == "$Record"
        ]
        for elem in self_updates:
            findings.append(
                Finding(
                    rule_id="FL003",
                    severity="warning",
                    file=flow.path,
                    element=elem.name,
                    message=(
                        f"Flow triggers on {start.record_trigger_type} of "
                        f"{start.object} with no entry criteria (filters), and "
                        f"'{elem.name}' updates the triggering record itself. "
                        "Every save re-invokes the flow, which updates the record "
                        "again, which re-invokes the flow — add entry criteria that "
                        "exclude the state you're setting, or this will recurse "
                        "until Salesforce's recursion limit throws a runtime error."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# FL004 — Dead automation
# ---------------------------------------------------------------------------

def rule_dead_automation(flows: list[Flow]) -> list[Finding]:
    findings = []
    for flow in flows:
        if not flow.is_active:
            continue
        if flow.is_record_triggered:
            # Record-triggered flows run automatically whenever their object
            # is saved — the platform invokes them by subscription, not by
            # name. They're never "referenced" the way a subflow/utility
            # flow is, so checking them here would flag nearly every
            # record-triggered flow in a healthy org. This rule targets
            # standalone autolaunched flows meant to be called by name
            # (subflow, Process Builder, Apex, a Flow button) that have lost
            # their last caller.
            continue
        referenced = False
        for other in flows:
            if other.path == flow.path:
                continue
            if flow.api_name in other.raw_text:
                referenced = True
                break
        if not referenced:
            findings.append(
                Finding(
                    rule_id="FL004",
                    severity="warning",
                    file=flow.path,
                    element=flow.api_name,
                    message=(
                        f"'{flow.api_name}' is Active but its API name does not "
                        "appear anywhere else in the scanned folder — no subflow "
                        "call, no Apex/LWC reference captured here, nothing. "
                        "Confirm this automation is still wired to something "
                        "(a Process Builder, a Platform Event, a button) before "
                        "trusting it; otherwise it's dead weight that still runs "
                        "on every record save."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# FL005 — Conflicting automation
# ---------------------------------------------------------------------------

def rule_conflicting_automation(flows: list[Flow]) -> list[Finding]:
    # key -> list of (flow, element)
    writers: dict[tuple[str, str, str], list[tuple[Flow, str]]] = {}
    for flow in flows:
        if not flow.is_active or not flow.is_record_triggered:
            continue
        obj = flow.start.object
        trigger = flow.start.record_trigger_type
        if not obj or not trigger:
            continue
        for elem in flow.dml_elements:
            if elem.kind != "recordUpdates":
                continue
            for write in elem.field_writes:
                key = (obj, trigger, write.field)
                writers.setdefault(key, []).append((flow, elem.name))

    findings = []
    for (obj, trigger, field_name), entries in writers.items():
        distinct_flows = {f.api_name for f, _ in entries}
        if len(distinct_flows) < 2:
            continue
        names = sorted(distinct_flows)
        for flow, elem_name in entries:
            others = sorted(n for n in distinct_flows if n != flow.api_name)
            findings.append(
                Finding(
                    rule_id="FL005",
                    severity="warning",
                    file=flow.path,
                    element=elem_name,
                    message=(
                        f"'{flow.api_name}' writes {obj}.{field_name} on "
                        f"{trigger}, and so does {', '.join(others)}. Two Active "
                        "flows on the same object/trigger writing the same field "
                        "race each other — the final value depends on flow "
                        f"execution order. All flows involved: {', '.join(names)}."
                    ),
                )
            )
    return findings


RULES = {
    "FL001": rule_missing_fault_path,
    "FL002": rule_hardcoded_id,
    "FL003": rule_recursion_risk,
    "FL004": rule_dead_automation,
    "FL005": rule_conflicting_automation,
}


def run_all_rules(flows: list[Flow], rule_ids: list[str] | None = None) -> list[Finding]:
    ids = rule_ids or list(RULES.keys())
    findings: list[Finding] = []
    for rid in ids:
        findings.extend(RULES[rid](flows))
    return findings
