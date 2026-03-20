"""
agents/agent_evaluation/tools.py
PDF report generation for the Evaluation Agent.

Generates a comparison table as a PDF using only the Python standard library
+ reportlab (lightweight PDF library).

Fallback: if reportlab is not installed, generates a plain-text .txt report.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from logger import get_logger

logger = get_logger(__name__)


def _fmt(value, fallback="N/A"):
    """Format a value for display, returning fallback if None."""
    if value is None:
        return fallback
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def generate_pdf_report(
    product: str,
    procurement_spec: dict,
    scores: list,
    output_dir: str = None,
) -> Optional[str]:
    """
    Generate a PDF comparison report for evaluated offers.

    Args:
        product: product name
        procurement_spec: the original procurement spec dict
        scores: list of OfferScore dataclasses (ranked)
        output_dir: output directory (default: outputs/)

    Returns:
        Path to the generated PDF file, or None on failure.
    """
    if not scores:
        return None

    out = Path(output_dir) if output_dir else PROJECT_ROOT / "outputs"
    out.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"evaluation_report_{ts}.pdf"
    filepath = out / filename

    try:
        return _generate_with_reportlab(filepath, product, procurement_spec, scores)
    except ImportError:
        logger.warning("reportlab not installed — falling back to text report")
        return _generate_text_report(filepath.with_suffix(".txt"), product, procurement_spec, scores)
    except Exception as exc:
        logger.error("PDF generation failed", extra={"error": str(exc)})
        return _generate_text_report(filepath.with_suffix(".txt"), product, procurement_spec, scores)


def _generate_with_reportlab(
    filepath: Path,
    product: str,
    spec: dict,
    scores: list,
) -> str:
    """Generate PDF using reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Table,
        TableStyle,
        Paragraph,
        Spacer,
    )

    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    elements = []

    # ── Title ────────────────────────────────────────────────────────────────
    elements.append(Paragraph("Supplier Evaluation Report", styles["Title"]))
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(f"Product: {product}", styles["Heading2"]))

    budget_max = spec.get("budget_max")
    quantity = spec.get("quantity")
    deadline = spec.get("deadline")
    info_parts = []
    if quantity:
        info_parts.append(f"Quantity: {quantity}")
    if budget_max:
        info_parts.append(f"Budget: {_fmt(budget_max)} {spec.get('currency', 'TND')}")
    if deadline:
        info_parts.append(f"Deadline: {deadline}")
    if info_parts:
        elements.append(Paragraph(" | ".join(info_parts), styles["Normal"]))
    elements.append(Spacer(1, 6 * mm))

    # ── Comparison table ─────────────────────────────────────────────────────
    header = [
        "Rank",
        "Supplier",
        "Unit Price",
        "Total Price",
        "Delivery\n(days)",
        "Warranty",
        "Payment\nTerms",
        "Price\nScore",
        "Delivery\nScore",
        "Warranty\nScore",
        "Payment\nScore",
        "Budget\nFit",
        "Overall\nScore",
    ]

    data = [header]
    for s in scores:
        row = [
            str(s.rank),
            s.supplier_name,
            _fmt(s.unit_price),
            _fmt(s.total_price),
            _fmt(s.delivery_days),
            s.warranty or "N/A",
            s.payment_terms or "N/A",
            f"{s.price_score:.1f}",
            f"{s.delivery_score:.1f}",
            f"{s.warranty_score:.1f}",
            f"{s.payment_score:.1f}",
            f"{s.budget_fit_score:.1f}",
            f"{s.overall_score:.1f}",
        ]
        data.append(row)

    col_widths = [30, 90, 60, 65, 45, 55, 55, 40, 45, 45, 45, 40, 45]
    table = Table(data, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # Body
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),   # Rank
        ("ALIGN", (2, 1), (-1, -1), "CENTER"),   # Numeric cols
        # Grid
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ECF0F1")]),
    ]

    # Highlight best row
    if len(data) > 1:
        style_cmds.append(
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#D5F5E3"))
        )

    table.setStyle(TableStyle(style_cmds))
    elements.append(table)
    elements.append(Spacer(1, 6 * mm))

    # ── Recommendations ──────────────────────────────────────────────────────
    elements.append(Paragraph("Recommendations", styles["Heading2"]))
    for s in scores:
        elements.append(
            Paragraph(
                f"<b>#{s.rank} {s.supplier_name}</b> (Score: {s.overall_score:.1f}/100): "
                f"{s.recommendation}",
                styles["Normal"],
            )
        )
        elements.append(Spacer(1, 2 * mm))

    # ── Footer ───────────────────────────────────────────────────────────────
    elements.append(Spacer(1, 8 * mm))
    elements.append(
        Paragraph(
            f"Generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
            f"— Procurement AI System",
            styles["Normal"],
        )
    )

    doc.build(elements)
    logger.info("PDF report generated", extra={"path": str(filepath)})
    return str(filepath)


def _generate_text_report(
    filepath: Path,
    product: str,
    spec: dict,
    scores: list,
) -> str:
    """Fallback: generate a plain-text report."""
    lines = [
        "=" * 70,
        "SUPPLIER EVALUATION REPORT",
        "=" * 70,
        f"Product : {product}",
        f"Quantity: {spec.get('quantity', 'N/A')}",
        f"Budget  : {_fmt(spec.get('budget_max'))}",
        f"Deadline: {spec.get('deadline', 'N/A')}",
        "",
        "-" * 70,
    ]

    for s in scores:
        lines.extend([
            f"Rank #{s.rank}: {s.supplier_name}",
            f"  Unit Price   : {_fmt(s.unit_price)}",
            f"  Total Price  : {_fmt(s.total_price)} {s.currency}",
            f"  Delivery     : {_fmt(s.delivery_days)} days",
            f"  Warranty     : {s.warranty or 'N/A'}",
            f"  Payment Terms: {s.payment_terms or 'N/A'}",
            f"  Scores → Price: {s.price_score:.1f}  Delivery: {s.delivery_score:.1f}"
            f"  Warranty: {s.warranty_score:.1f}  Payment: {s.payment_score:.1f}"
            f"  Budget Fit: {s.budget_fit_score:.1f}",
            f"  Overall Score: {s.overall_score:.1f} / 100",
            f"  Recommendation: {s.recommendation}",
            "-" * 70,
        ])

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"\nGenerated on {ts} — Procurement AI System")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Text report generated (fallback)", extra={"path": str(filepath)})
    return str(filepath)
