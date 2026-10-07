import os
import io
import csv
from typing import List, Dict, Any, Optional
import pandas as pd

import config
import database
from temporal_engine import ViolationType, SeverityLevel, ViolationStatus
from ppe_association import PPEState

# Standard Mapping for readable violation labels
VIOLATION_LABEL_MAP = {
    "MISSING_HELMET": "Missing Helmet",
    "MISSING_VEST": "Missing Vest",
    "MISSING_GLOVES": "Missing Gloves",
    "MISSING_BOOTS": "Missing Boots",
    "MISSING_GOGGLES": "Missing Goggles",
    ViolationType.MISSING_HELMET.value: "Missing Helmet",
    ViolationType.MISSING_VEST.value: "Missing Vest",
    ViolationType.MISSING_GLOVES.value: "Missing Gloves",
    ViolationType.MISSING_BOOTS.value: "Missing Boots",
    ViolationType.MISSING_GOGGLES.value: "Missing Goggles",
}

# Reverse mapping for filtering
LABEL_TO_VIOLATION_VAL = {v: k for k, v in VIOLATION_LABEL_MAP.items() if "_" in k}

SEVERITY_BADGES = {
    "CRITICAL": "🔴 CRITICAL",
    "HIGH": "🟠 HIGH",
    "MEDIUM": "🟡 MEDIUM",
    "LOW": "🔵 LOW",
    "NONE": "⚪ NONE",
}

PPE_DISPLAY_STATUS = {
    PPEState.PRESENT: "✅ PRESENT",
    PPEState.NOT_ASSOCIATED: "❌ NOT ASSOCIATED",
    PPEState.UNKNOWN: "❓ UNKNOWN",
    "PRESENT": "✅ PRESENT",
    "NOT_ASSOCIATED": "❌ NOT ASSOCIATED",
    "UNKNOWN": "❓ UNKNOWN",
}

CSV_EXPORT_COLUMNS = [
    "event_id",
    "track_id",
    "violation_type",
    "severity",
    "decision_score",
    "evidence_path",
    "timestamp",
    "status",
    "frame_index",
    "missing_ratio",
    "observable_frames",
    "is_zone_violation",
    "message",
]


def format_violation_type(vtype: Any) -> str:
    """Returns human-readable representation of violation type."""
    val = vtype.value if hasattr(vtype, "value") else str(vtype)
    return VIOLATION_LABEL_MAP.get(val, val)


def format_severity(severity: Any) -> str:
    """Returns formatted severity string."""
    val = severity.value if hasattr(severity, "value") else str(severity)
    return val.upper()


def format_ppe_status(state: Any) -> str:
    """
    Formats PPE status according to strict Phase 7 rules:
    ✅ PRESENT
    ❌ NOT ASSOCIATED
    ❓ UNKNOWN
    """
    if hasattr(state, "value"):
        val = state.value
    else:
        val = str(state)
    return PPE_DISPLAY_STATUS.get(val, "❓ UNKNOWN")


def load_violation_history(limit: int = 500, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Loads confirmed violation records from SQLite database."""
    try:
        return database.get_recent_violations(limit=limit, db_path=db_path)
    except Exception:
        return []


def filter_violations(
    violations: List[Dict[str, Any]],
    severity_filter: str = "All",
    violation_type_filter: str = "All",
    worker_id_filter: str = "All",
) -> List[Dict[str, Any]]:
    """
    Applies multi-attribute filtering over violation dictionaries in-memory.
    """
    if not violations:
        return []

    filtered = []
    for item in violations:
        # 1. Severity filter
        if severity_filter != "All":
            item_sev = str(item.get("severity", "")).upper()
            if item_sev != severity_filter.upper():
                continue

        # 2. Violation type filter
        if violation_type_filter != "All":
            raw_vtype = str(item.get("violation_type", ""))
            readable_vtype = format_violation_type(raw_vtype)
            if (
                violation_type_filter.upper() != raw_vtype.upper()
                and violation_type_filter.lower() != readable_vtype.lower()
            ):
                continue

        # 3. Worker ID filter
        if worker_id_filter != "All":
            try:
                worker_int = int(worker_id_filter)
                if item.get("track_id") != worker_int:
                    continue
            except ValueError:
                if str(item.get("track_id")) != str(worker_id_filter):
                    continue

        filtered.append(item)

    return filtered


def export_violations_csv(violations: List[Dict[str, Any]]) -> str:
    """
    Exports violation records into a CSV formatted string matching the Phase 7 spec:
    event_id, track_id, violation_type, severity, decision_score, evidence_path,
    timestamp, status, frame_index, missing_ratio, observable_frames,
    is_zone_violation, message.
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_EXPORT_COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()

    for v in violations:
        row = {}
        for col in CSV_EXPORT_COLUMNS:
            row[col] = v.get(col, "")
        writer.writerow(row)

    return output.getvalue()


def check_evidence_file(evidence_path: Optional[str]) -> bool:
    """Checks whether the given evidence file exists and is readable."""
    if not evidence_path:
        return False
    return os.path.exists(evidence_path) and os.path.isfile(evidence_path)
