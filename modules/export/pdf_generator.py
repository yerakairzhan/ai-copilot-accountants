"""
PDF Tax Package Generator.
Uses ReportLab to produce a clean, printable document.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import os
from datetime import datetime


# ─── Helpers ─────────────────────────────────────────────────────────────────

CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E",
    "Ж": "Zh", "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M",
    "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
    "Ф": "F", "Х": "Kh", "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Sch", "Ъ": "",
    "Ы": "Y", "Ь": "", "Э": "E", "Ю": "Yu", "Я": "Ya",
    "қ": "q", "Қ": "Q", "ғ": "gh", "Ғ": "Gh", "ә": "a", "Ә": "A",
    "ң": "ng", "Ң": "Ng", "ө": "o", "Ө": "O", "ұ": "u", "Ұ": "U",
    "ү": "u", "Ү": "U", "һ": "h", "Һ": "H", "і": "i", "І": "I",
}

def _styles():
    styles = getSampleStyleSheet()
    custom = {
        "Title": ParagraphStyle("Title", fontSize=16, spaceAfter=6,
                                textColor=colors.HexColor("#1a1a2e"), alignment=TA_CENTER,
                                fontName="Helvetica-Bold"),
        "Subtitle": ParagraphStyle("Subtitle", fontSize=11, spaceAfter=4,
                                   textColor=colors.HexColor("#444"), alignment=TA_CENTER),
        "Heading": ParagraphStyle("Heading", fontSize=12, spaceBefore=12, spaceAfter=4,
                                  textColor=colors.HexColor("#1a1a2e"), fontName="Helvetica-Bold"),
        "Body": ParagraphStyle("Body", fontSize=9, spaceAfter=3, fontName="Helvetica"),
        "Small": ParagraphStyle("Small", fontSize=8, textColor=colors.grey),
        "RiskHigh": ParagraphStyle("RiskHigh", fontSize=9, textColor=colors.HexColor("#c0392b")),
        "RiskMedium": ParagraphStyle("RiskMedium", fontSize=9, textColor=colors.HexColor("#e67e22")),
        "RiskLow": ParagraphStyle("RiskLow", fontSize=9, textColor=colors.HexColor("#2980b9")),
    }
    return {**{k: styles[k] for k in styles.byName}, **custom}


def _fmt_money(amount: float) -> str:
    return f"{amount:,.2f} KZT".replace(",", " ")


def _severity_color(sev: str) -> colors.Color:
    return {
        "high": colors.HexColor("#c0392b"),
        "medium": colors.HexColor("#e67e22"),
        "low": colors.HexColor("#2980b9"),
    }.get(sev, colors.grey)


def _latinize(text) -> str:
    raw = str(text or "")
    converted = "".join(CYRILLIC_TO_LATIN.get(ch, ch) for ch in raw)
    return converted[:500]


# ─── Main Generator ───────────────────────────────────────────────────────────

def generate_tax_package(
    output_path: str,
    client: dict,
    period: dict,
    transactions: list[dict],
    risks: list[dict],
    summary: dict,
) -> str:
    """
    Generate the final tax package PDF.
    Returns path to the created file.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    S = _styles()
    story = []

    # ── Cover ──
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("TAX PACKAGE", S["Title"]))
    story.append(Paragraph(
        f"Client: {_latinize(client.get('name', ''))} | BIN/IIN: {client.get('bin', '')} | Regime: USN",
        S["Subtitle"]
    ))
    story.append(Paragraph(
        f"Period: {period.get('quarter', '')} {period.get('year', '')}",
        S["Subtitle"]
    ))
    story.append(Paragraph(
        f"Generated at: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        S["Small"]
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#ccc"), spaceAfter=12))

    # ── Summary ──
    story.append(Paragraph("1. Tax Summary", S["Heading"]))

    open_risks = [r for r in risks if r.get("status") == "open"]
    high_risks = [r for r in open_risks if r.get("severity") == "high"]

    summary_data = [
        ["Metric", "Amount"],
        ["Income (tax base)", _fmt_money(summary["income"])],
        [f"USN tax ({int(summary['tax_rate'] * 100)}%)", _fmt_money(summary["tax"])],
        ["Expenses (for analysis)", _fmt_money(summary["expenses"])],
        ["Personal transactions (excluded)", _fmt_money(summary["personal"])],
        ["Unclassified", _fmt_money(summary["unclassified"])],
    ]

    t = Table(summary_data, colWidths=[10 * cm, 6 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#fff3cd")),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)

    if high_risks:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"Warning: {len(high_risks)} high-risk items should be resolved before filing.",
            S["RiskHigh"]
        ))

    story.append(Spacer(1, 0.5 * cm))

    # ── Transactions ──
    story.append(Paragraph("2. Transactions", S["Heading"]))

    approved = [tx for tx in transactions if tx.get("approved_by")]
    pending = [tx for tx in transactions if not tx.get("approved_by")]

    if pending:
        story.append(Paragraph(
            f"Warning: {len(pending)} transactions are not approved by the accountant.",
            S["RiskHigh"]
        ))
        story.append(Spacer(1, 4))

    tx_header = [["Date", "Counterparty / Description", "Amount", "Category", "Status"]]
    tx_rows = []

    for tx in transactions:
        cat_map = {
            "income": "Income",
            "expense": "Expense",
            "personal": "Personal",
            None: "—",
        }
        status = "Approved" if tx.get("approved_by") else "Pending"
        desc = _latinize((tx.get("counterparty") or tx.get("description") or ""))[:40]
        amount_str = _fmt_money(tx.get("amount", 0))
        if tx.get("direction") == "in":
            amount_str = "+ " + amount_str
        elif tx.get("direction") == "out":
            amount_str = "- " + amount_str

        tx_rows.append([
            str(tx.get("date", ""))[:10],
            desc,
            amount_str,
            cat_map.get(tx.get("category"), "—"),
            status,
        ])

    all_rows = tx_header + tx_rows
    tx_table = Table(all_rows, colWidths=[2.2 * cm, 6 * cm, 3.5 * cm, 2.5 * cm, 2.8 * cm])
    tx_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ddd")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("WORDWRAP", (1, 1), (1, -1), True),
    ]

    # Color unapproved rows
    for i, tx in enumerate(transactions, start=1):
        if not tx.get("approved_by"):
            tx_style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fff3cd")))

    tx_table.setStyle(TableStyle(tx_style))
    story.append(tx_table)
    story.append(Spacer(1, 0.5 * cm))

    # ── Risks ──
    story.append(Paragraph("3. Tax Risks", S["Heading"]))

    if not risks:
        story.append(Paragraph("No risks detected.", S["Body"]))
    else:
        sev_labels = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
        status_labels = {"open": "Open", "resolved": "Resolved", "ignored": "Ignored"}

        risk_data = [["#", "Severity", "Description", "Status"]]
        for i, r in enumerate(risks, 1):
            risk_data.append([
                str(i),
                sev_labels.get(r["severity"], r["severity"]),
                _latinize(r.get("description", "")),
                status_labels.get(r.get("status", "open"), r.get("status", "open")),
            ])

        risk_table = Table(risk_data, colWidths=[0.7 * cm, 2.5 * cm, 10 * cm, 2.8 * cm])
        risk_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ddd")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for i, r in enumerate(risks, 1):
            col = _severity_color(r["severity"])
            risk_style.append(("TEXTCOLOR", (1, i), (1, i), col))
            risk_style.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))
            if r.get("status") == "open":
                risk_style.append(("BACKGROUND", (0, i), (-1, i),
                                    colors.HexColor("#ffeeee") if r["severity"] == "high" else colors.white))

        risk_table.setStyle(TableStyle(risk_style))
        story.append(risk_table)

    story.append(Spacer(1, 0.5 * cm))

    # ── Footer ──
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#ccc")))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Document generated by AI Copilot for Accountants. "
        "Requires accountant review and confirmation before filing.",
        S["Small"]
    ))

    doc.build(story)
    return output_path
