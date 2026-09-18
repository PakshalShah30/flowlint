"""Parses Salesforce Flow metadata XML (.flow-meta.xml) into flowlint models.

Salesforce Flow metadata lives in the ``http://soap.sforce.com/2006/04/metadata``
namespace. We use the standard-library ``xml.etree.ElementTree`` rather than a
third-party XML library — Flow metadata files are small, trusted (they come
from the user's own repo), and ElementTree's namespace handling is more than
enough for the flat, well-documented structure Salesforce generates. This
keeps FlowLint dependency-free.
"""

from __future__ import annotations

import glob
import os
import xml.etree.ElementTree as ET

from .models import DmlElement, FieldWrite, Flow, NamedNode, StartInfo, DML_KINDS

SF_NS = "http://soap.sforce.com/2006/04/metadata"

# Direct children of <Flow> that represent an addressable "node" in the flow
# canvas (i.e. they carry a <name> element). We scan the raw XML of each of
# these for hardcoded-ID literals so findings can be attributed to a specific
# element instead of just "somewhere in this file".
NAMED_NODE_TAGS = {
    "recordCreates",
    "recordUpdates",
    "recordDeletes",
    "recordLookups",
    "assignments",
    "decisions",
    "subflows",
    "variables",
    "constants",
    "formulas",
    "textTemplates",
    "loops",
    "actionCalls",
    "waits",
    "screens",
    "collectionProcessors",
    "recordRollbacks",
    "stages",
}


def _local(tag: str) -> str:
    """Strip the XML namespace off a tag, e.g. '{ns}Flow' -> 'Flow'."""
    return tag.rsplit("}", 1)[-1]


def _child(elem: ET.Element, name: str) -> ET.Element | None:
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in elem if _local(c.tag) == name]


def _text(elem: ET.Element | None) -> str | None:
    if elem is None:
        return None
    return (elem.text or "").strip() or None


def find_flow_files(root_path: str) -> list[str]:
    """Return every *.flow-meta.xml file under root_path (file or directory)."""
    if os.path.isfile(root_path):
        return [root_path]
    pattern = os.path.join(root_path, "**", "*.flow-meta.xml")
    return sorted(glob.glob(pattern, recursive=True))


def _api_name_from_path(path: str) -> str:
    base = os.path.basename(path)
    return base[: -len(".flow-meta.xml")] if base.endswith(".flow-meta.xml") else base


def _parse_start(root: ET.Element) -> StartInfo:
    start_elem = _child(root, "start")
    info = StartInfo()
    if start_elem is None:
        return info
    info.object = _text(_child(start_elem, "object"))
    info.record_trigger_type = _text(_child(start_elem, "recordTriggerType"))
    info.trigger_type = _text(_child(start_elem, "triggerType"))
    info.has_filters = len(_children(start_elem, "filters")) > 0
    return info


def _parse_field_writes(elem: ET.Element) -> list[FieldWrite]:
    writes = []
    for assignment in _children(elem, "inputAssignments"):
        field_name = _text(_child(assignment, "field"))
        if field_name is None:
            continue
        value_elem = _child(assignment, "value")
        value_text = None
        if value_elem is not None and len(value_elem) > 0:
            # value wraps one typed child: stringValue, elementReference, etc.
            value_text = _text(value_elem[0])
        writes.append(FieldWrite(field=field_name, value=value_text))
    return writes


def _parse_dml_elements(root: ET.Element) -> list[DmlElement]:
    elements = []
    for kind in DML_KINDS:
        for node in _children(root, kind):
            name = _text(_child(node, "name")) or "(unnamed)"
            has_fault = _child(node, "faultConnector") is not None
            input_ref = _text(_child(node, "inputReference"))
            object_ref = _text(_child(node, "object"))
            writes = _parse_field_writes(node)
            elements.append(
                DmlElement(
                    name=name,
                    kind=kind,
                    has_fault_connector=has_fault,
                    input_reference=input_ref,
                    object_ref=object_ref,
                    field_writes=writes,
                )
            )
    return elements


def _parse_named_nodes(root: ET.Element) -> list[NamedNode]:
    nodes = []
    for child in root:
        tag = _local(child.tag)
        if tag not in NAMED_NODE_TAGS:
            continue
        name = _text(_child(child, "name")) or tag
        raw_xml = ET.tostring(child, encoding="unicode")
        nodes.append(NamedNode(name=name, tag=tag, raw_xml=raw_xml))
    return nodes


def parse_flow(path: str) -> Flow:
    with open(path, "r", encoding="utf-8") as fh:
        raw_text = fh.read()

    tree = ET.parse(path)
    root = tree.getroot()

    return Flow(
        path=path,
        api_name=_api_name_from_path(path),
        label=_text(_child(root, "label")),
        status=_text(_child(root, "status")),
        process_type=_text(_child(root, "processType")),
        start=_parse_start(root),
        dml_elements=_parse_dml_elements(root),
        named_nodes=_parse_named_nodes(root),
        raw_text=raw_text,
    )


def parse_all(root_path: str) -> list[Flow]:
    flows = []
    for path in find_flow_files(root_path):
        try:
            flows.append(parse_flow(path))
        except ET.ParseError as exc:
            raise ValueError(f"Could not parse {path}: {exc}") from exc
    return flows
