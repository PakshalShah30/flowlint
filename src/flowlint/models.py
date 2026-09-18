"""Data structures shared by the parser, rules, and reporter."""

from __future__ import annotations

from dataclasses import dataclass, field


DML_KINDS = ("recordCreates", "recordUpdates", "recordDeletes", "recordLookups")

# Human-friendly labels for the DML kinds above, used in finding messages.
DML_LABELS = {
    "recordCreates": "Create Records",
    "recordUpdates": "Update Records",
    "recordDeletes": "Delete Records",
    "recordLookups": "Get Records",
}


@dataclass
class FieldWrite:
    """A single `field` -> literal value assignment inside a DML element."""

    field: str
    value: str | None


@dataclass
class DmlElement:
    """A recordCreates / recordUpdates / recordDeletes / recordLookups node."""

    name: str
    kind: str  # one of DML_KINDS
    has_fault_connector: bool
    input_reference: str | None  # e.g. "$Record" for record-triggered updates
    object_ref: str | None  # explicit <object> on the element, if present
    field_writes: list[FieldWrite] = field(default_factory=list)


@dataclass
class NamedNode:
    """Any flow node that has a <name> child (used for hardcoded-ID scanning)."""

    name: str
    tag: str
    raw_xml: str


@dataclass
class StartInfo:
    object: str | None = None
    record_trigger_type: str | None = None  # Create, Update, CreateAndUpdate, Delete
    trigger_type: str | None = None
    has_filters: bool = False


@dataclass
class Flow:
    """A parsed .flow-meta.xml file."""

    path: str
    api_name: str
    label: str | None
    status: str | None
    process_type: str | None
    start: StartInfo
    dml_elements: list[DmlElement] = field(default_factory=list)
    named_nodes: list[NamedNode] = field(default_factory=list)
    raw_text: str = ""

    @property
    def is_active(self) -> bool:
        return (self.status or "").strip() == "Active"

    @property
    def is_record_triggered(self) -> bool:
        return bool(self.start.object) and bool(self.start.record_trigger_type)


@dataclass
class Finding:
    rule_id: str
    severity: str  # "error" | "warning"
    file: str
    element: str | None
    message: str

    def as_dict(self) -> dict:
        return {
            "rule": self.rule_id,
            "severity": self.severity,
            "file": self.file,
            "element": self.element,
            "message": self.message,
        }
