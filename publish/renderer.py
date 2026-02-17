"""Renderer — transforms JSON artifacts into Markdown and CSV outputs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def _md_h1(text: str) -> str:
    return f"# {text}\n\n"


def _md_h2(text: str) -> str:
    return f"## {text}\n\n"


def _md_h3(text: str) -> str:
    return f"### {text}\n\n"


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Build a Markdown table from headers and rows."""
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines) + "\n\n"


def _md_bullet(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) + "\n\n"


# ---------------------------------------------------------------------------
# Certification renderer
# ---------------------------------------------------------------------------

def render_cert_markdown(state: dict[str, Any]) -> str:
    """Render certification artifacts to Markdown."""
    parts: list[str] = []
    scope_id = state.get("scope_id", "unknown")
    version = state.get("manifest", {}).get("version", "")

    parts.append(_md_h1(f"Certification: {scope_id}"))
    if version:
        parts.append(f"**Version:** {version}\n\n")

    # Objective map
    objectives = state.get("objectives", [])
    if objectives:
        parts.append(_md_h2("Objective Map"))
        rows = []
        for obj in objectives:
            rows.append([
                obj.get("code", ""),
                obj.get("text", ""),
                str(obj.get("weight", "")),
            ])
        parts.append(_md_table(["Code", "Objective", "Weight"], rows))

    # Lesson modules
    modules = state.get("modules", [])
    if modules:
        parts.append(_md_h2("Lesson Modules"))
        for mod in modules:
            parts.append(_md_h3(f"{mod.get('title', 'Untitled')} ({mod.get('level', '')})"))
            parts.append(f"**Objective:** {mod.get('objective_id', '')}\n\n")
            content = mod.get("content_json", {})
            sections = content.get("sections", [])
            if sections:
                parts.append(_md_bullet(sections))
            refs = content.get("claim_refs", [])
            if refs:
                parts.append(f"*Grounded in claims: {', '.join(refs)}*\n\n")

    # Question bank
    questions = state.get("questions", [])
    if questions:
        parts.append(_md_h2("Question Bank"))
        for i, q in enumerate(questions, 1):
            content = q.get("content_json", {})
            parts.append(_md_h3(f"Q{i}: {content.get('question', '')}"))
            parts.append(f"**Type:** {q.get('qtype', '')}")
            parts.append(f" | **Objective:** {q.get('objective_id', '')}\n\n")
            options = content.get("options", [])
            if options:
                for opt in options:
                    parts.append(f"- {opt}\n")
                parts.append("\n")
            parts.append(f"**Answer:** {content.get('correct_answer', '')}\n\n")
            parts.append(f"*Explanation: {content.get('explanation', '')}*\n\n")

    # Changelog / delta memo
    delta = state.get("delta_json", {})
    if delta:
        parts.append(_md_h2("Changelog"))
        added = delta.get("added_claims", [])
        removed = delta.get("removed_claims", [])
        changed = delta.get("changed_claims", [])
        if added:
            parts.append(f"**Added claims:** {', '.join(added)}\n\n")
        if removed:
            parts.append(f"**Removed claims:** {', '.join(removed)}\n\n")
        if changed:
            parts.append(f"**Changed claims:** {', '.join(changed)}\n\n")
        stability = state.get("stability_score")
        if stability is not None:
            parts.append(f"**Stability score:** {stability}\n\n")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Dossier renderer
# ---------------------------------------------------------------------------

def render_dossier_markdown(state: dict[str, Any]) -> str:
    """Render dossier artifacts to Markdown."""
    parts: list[str] = []
    scope_id = state.get("scope_id", "unknown")
    version = state.get("manifest", {}).get("version", "")

    parts.append(_md_h1(f"Living Dossier: {scope_id}"))
    if version:
        parts.append(f"**Snapshot:** {version}\n\n")

    # Synthesis summary
    synthesis = state.get("synthesis", {})
    if synthesis:
        parts.append(_md_h2("Summary"))
        parts.append(f"{synthesis.get('summary', '')}\n\n")
        findings = synthesis.get("key_findings", [])
        if findings:
            parts.append(_md_h3("Key Findings"))
            items = []
            for f in findings:
                cites = f.get("claim_ids", [])
                cite_str = f" (claims: {', '.join(cites)})" if cites else ""
                items.append(f"{f.get('finding', '')}{cite_str}")
            parts.append(_md_bullet(items))

    # Timeline (delta changes)
    delta = state.get("delta_json", {})
    if delta:
        parts.append(_md_h2("What Changed"))
        added = delta.get("added_claims", [])
        removed = delta.get("removed_claims", [])
        changed = delta.get("changed_claims", [])
        if added:
            parts.append(f"**New claims:** {', '.join(added)}\n\n")
        if removed:
            parts.append(f"**Removed:** {', '.join(removed)}\n\n")
        if changed:
            parts.append(f"**Updated:** {', '.join(changed)}\n\n")

    # Metric tables
    metrics = state.get("metrics", [])
    points = state.get("metric_points", [])
    if metrics and points:
        parts.append(_md_h2("Metrics"))
        metric_lookup = {m.get("metric_id"): m for m in metrics}
        rows = []
        for pt in points:
            m = metric_lookup.get(pt.get("metric_id"), {})
            rows.append([
                m.get("name", pt.get("metric_id", "")),
                str(pt.get("value", "")),
                m.get("unit", ""),
                pt.get("t", ""),
                str(pt.get("confidence", "")),
            ])
        parts.append(_md_table(["Metric", "Value", "Unit", "Period", "Confidence"], rows))

    # Contradictions
    contradictions = state.get("contradictions", [])
    if contradictions:
        parts.append(_md_h2("Contradictions"))
        for c in contradictions:
            parts.append(f"- **{c.get('claim_a_id', '')}** vs **{c.get('claim_b_id', '')}**: "
                         f"{c.get('reason', '')}\n")
        parts.append("\n")

    # Claim status
    claims = state.get("claims", [])
    if claims:
        parts.append(_md_h2("Claims"))
        rows = []
        for cl in claims:
            rows.append([
                cl.get("claim_id", ""),
                cl.get("statement", ""),
                cl.get("status", ""),
                str(cl.get("confidence", "")),
            ])
        parts.append(_md_table(["ID", "Statement", "Status", "Confidence"], rows))

    return "".join(parts)


# ---------------------------------------------------------------------------
# Lab renderer
# ---------------------------------------------------------------------------

def render_lab_markdown(state: dict[str, Any]) -> str:
    """Render lab artifacts to Markdown."""
    parts: list[str] = []
    scope_id = state.get("scope_id", "unknown")
    version = state.get("manifest", {}).get("version", "")

    parts.append(_md_h1(f"AI Lab Report: {scope_id}"))
    if version:
        parts.append(f"**Suite version:** {version}\n\n")

    # Hardware spec
    hw = state.get("hw_spec", {})
    if hw:
        parts.append(_md_h2("Hardware"))
        items = [f"{k}: {v}" for k, v in hw.items()]
        parts.append(_md_bullet(items))

    # Models tested
    models = state.get("models", [])
    if models:
        parts.append(_md_h2("Models"))
        rows = [[m.get("model_id", "")] for m in models]
        parts.append(_md_table(["Model ID"], rows))

    # Synthesis / benchmark results
    synthesis = state.get("synthesis", {})
    if synthesis:
        parts.append(_md_h2("Benchmark Summary"))
        parts.append(f"{synthesis.get('summary', '')}\n\n")
        if synthesis.get("metrics_summary"):
            parts.append(f"**Metrics:** {synthesis['metrics_summary']}\n\n")

        # Scores table
        scores = synthesis.get("scores", {})
        if scores:
            parts.append(_md_h3("Scores"))
            rows = [[model, str(score)] for model, score in scores.items()]
            parts.append(_md_table(["Model", "Score"], rows))

        # Routing recommendations
        routing = synthesis.get("routing_config", {})
        if routing:
            parts.append(_md_h3("Routing Recommendations"))
            rec = routing.get("recommended", {})
            if rec:
                rows = [[task, model] for task, model in rec.items()]
                parts.append(_md_table(["Task Category", "Recommended Model"], rows))
            if routing.get("local_threshold"):
                parts.append(f"**Local threshold:** {routing['local_threshold']}\n\n")
            if routing.get("frontier_threshold"):
                parts.append(f"**Frontier threshold:** {routing['frontier_threshold']}\n\n")

    # Trend metrics
    metrics = state.get("metrics", [])
    points = state.get("metric_points", [])
    if metrics and points:
        parts.append(_md_h2("Trend Metrics"))
        metric_lookup = {m.get("metric_id"): m for m in metrics}
        rows = []
        for pt in points:
            m = metric_lookup.get(pt.get("metric_id"), {})
            rows.append([
                m.get("name", pt.get("metric_id", "")),
                str(pt.get("value", "")),
                m.get("unit", ""),
                pt.get("t", ""),
            ])
        parts.append(_md_table(["Metric", "Value", "Unit", "Period"], rows))

    # Delta memo
    delta = state.get("delta_json", {})
    if delta:
        parts.append(_md_h2("Changes"))
        added = delta.get("added_claims", [])
        if added:
            parts.append(f"**New data points:** {len(added)}\n\n")

    return "".join(parts)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _to_csv(headers: list[str], rows: list[list[str]]) -> str:
    """Write headers + rows to a CSV string with consistent line endings."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue()


def export_cert_modules_csv(modules: list[dict]) -> str:
    """Export certification modules to CSV."""
    headers = ["module_id", "objective_id", "level", "title"]
    rows = []
    for m in modules:
        rows.append([
            m.get("module_id", ""),
            m.get("objective_id", ""),
            m.get("level", ""),
            m.get("title", ""),
        ])
    return _to_csv(headers, rows)


def export_cert_questions_csv(questions: list[dict]) -> str:
    """Export certification questions to CSV."""
    headers = ["question_id", "objective_id", "qtype", "question", "correct_answer",
               "grounding_claim_ids"]
    rows = []
    for q in questions:
        content = q.get("content_json", {})
        rows.append([
            q.get("question_id", ""),
            q.get("objective_id", ""),
            q.get("qtype", ""),
            content.get("question", ""),
            content.get("correct_answer", ""),
            ";".join(q.get("grounding_claim_ids", [])),
        ])
    return _to_csv(headers, rows)


# ---------------------------------------------------------------------------
# Top-level render dispatcher
# ---------------------------------------------------------------------------

def render_markdown(scope_type: str, state: dict[str, Any]) -> str:
    """Dispatch to the appropriate renderer based on scope_type."""
    if scope_type == "cert":
        return render_cert_markdown(state)
    elif scope_type == "topic":
        return render_dossier_markdown(state)
    elif scope_type == "lab":
        return render_lab_markdown(state)
    else:
        raise ValueError(f"Unknown scope_type for rendering: {scope_type}")


def _write_artifact(path: Path, content: str) -> str:
    """Write content to file and return its sha256 hash. Uses binary mode for consistent hashing."""
    data = content.encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def render_exports(scope_type: str, state: dict[str, Any], publish_dir: Path) -> list[dict]:
    """Render all export formats for a scope_type. Returns artifact metadata list."""
    artifacts: list[dict] = []

    # Markdown for all scope types
    md = render_markdown(scope_type, state)
    md_path = publish_dir / "report.md"
    md_hash = _write_artifact(md_path, md)
    artifacts.append({
        "name": "report.md",
        "path": str(md_path),
        "hash": md_hash,
        "format": "markdown",
    })

    # CSV exports for certification only
    if scope_type == "cert":
        modules = state.get("modules", [])
        if modules:
            csv_content = export_cert_modules_csv(modules)
            csv_path = publish_dir / "modules.csv"
            csv_hash = _write_artifact(csv_path, csv_content)
            artifacts.append({
                "name": "modules.csv",
                "path": str(csv_path),
                "hash": csv_hash,
                "format": "csv",
            })

        questions = state.get("questions", [])
        if questions:
            csv_content = export_cert_questions_csv(questions)
            csv_path = publish_dir / "questions.csv"
            csv_hash = _write_artifact(csv_path, csv_content)
            artifacts.append({
                "name": "questions.csv",
                "path": str(csv_path),
                "hash": csv_hash,
                "format": "csv",
            })

    return artifacts
