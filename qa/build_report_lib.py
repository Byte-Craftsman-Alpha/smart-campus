"""Build the testing report (DOCX + PDF) from the real result files.

Nothing in the report is typed by hand: the suite totals, the per-case rows and
the screenshots all come from qa/results/*.json and docs/testing/screenshots/.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "qa" / "results"
SHOTS = ROOT / "docs" / "testing" / "screenshots"
OUT_DIR = ROOT / "docs" / "testing"

NAVY = RGBColor(0x16, 0x26, 0x4D)
NAVY_HEX = "16264D"
INK = RGBColor(0x1B, 0x1F, 0x27)
INK2 = RGBColor(0x46, 0x50, 0x5F)
INK3 = RGBColor(0x6D, 0x78, 0x87)
TEAL = RGBColor(0x0C, 0x6E, 0x6E)
TEAL_HEX = "0C6E6E"
AMBER = RGBColor(0xA5, 0x6A, 0x11)
AMBER_HEX = "FBF2E1"
ROSE = RGBColor(0x9E, 0x2F, 0x32)
ROSE_HEX = "FBEBEA"
GREEN = RGBColor(0x1E, 0x6F, 0x45)
GREEN_HEX = "E6F3EC"
RULE = "D8DEE8"
BAND = "F5F7FC"
TINT_NAVY = "EDF1FA"
TINT_TEAL = "E3F2F1"

DISPLAY = "Georgia"
BODY = "Segoe UI"
MONO = "Consolas"


# ----------------------------------------------------------------- helpers
def shade(cell, hex_fill: str):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def cell_borders(cell, colour=RULE, sz=4, edges=("top", "left", "bottom", "right")):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = tcPr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcPr.append(borders)
    for edge in edges:
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), str(sz))
        element.set(qn("w:color"), colour)
        borders.append(element)


def no_borders(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "nil")
        borders.append(element)
    tcPr.append(borders)


def run(par, text, size=10, bold=False, italic=False, colour=INK, font=BODY):
    r = par.add_run(text)
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.color.rgb = colour
    r.font.name = font
    return r


def para(doc, text="", size=10, bold=False, italic=False, colour=INK, font=BODY,
         space_before=0, space_after=6, align=None, line=1.18):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.line_spacing = line
    if align is not None:
        p.alignment = align
    if text:
        run(p, text, size=size, bold=bold, italic=italic, colour=colour, font=font)
    return p


def spacer(doc, points=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    run(p, "", size=points)


def band(doc, title, eyebrow=None, fill=NAVY_HEX, height=None):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.cell(0, 0)
    shade(cell, fill)
    no_borders(cell)
    cell.width = Cm(16.6)
    if eyebrow:
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        run(p, eyebrow.upper(), size=7.5, bold=True, colour=RGBColor(0x9F, 0xB4, 0xE8))
    p = cell.paragraphs[-1]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(10)
    run(p, title, size=16, bold=True, colour=RGBColor(0xFF, 0xFF, 0xFF), font=DISPLAY)
    return table


def h1(doc, text, number=None):
    doc.add_page_break()
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    widths = (Cm(1.6), Cm(15.0))
    for i, cell in enumerate(table.rows[0].cells):
        cell.width = widths[i]
        shade(cell, NAVY_HEX)
        no_borders(cell)
    if number:
        p = table.cell(0, 0).paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run(p, str(number), size=15, bold=True, colour=RGBColor(0x9F, 0xB4, 0xE8))
    p = table.cell(0, 1).paragraphs[0]
    run(p, text, size=13, bold=True, colour=RGBColor(0xFF, 0xFF, 0xFF), font=DISPLAY)
    spacer(doc, 8)


def h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    run(p, text, size=11.5, bold=True, colour=NAVY, font=DISPLAY)


def h3(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(9)
    p.paragraph_format.space_after = Pt(2)
    run(p, text, size=10, bold=True, colour=TEAL)


def bullet(doc, text, size=9.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.14
    run(p, text, size=size)
    return p


def numbered(doc, text, size=9.5):
    p = doc.add_paragraph(style="List Number")
    p.paragraph_format.space_after = Pt(3)
    run(p, text, size=size)
    return p


def callout(doc, text, fill=TINT_TEAL, bar=TEAL_HEX, label=None):
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    bar_cell, body = table.cell(0, 0), table.cell(0, 1)
    bar_cell.width = Cm(0.16)
    body.width = Cm(16.2)
    shade(bar_cell, bar)
    no_borders(bar_cell)
    shade(body, fill)
    cell_borders(body, colour=fill, sz=2)
    p = body.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    if label:
        run(p, label.upper(), size=7.5, bold=True, colour=TEAL)
        p2 = body.add_paragraph()
        p2.paragraph_format.space_after = Pt(2)
        run(p2, text, size=9.5, colour=INK)
    else:
        run(p, text, size=9.5, colour=INK)
    spacer(doc, 6)


def table(doc, headers, rows, widths=None, size=8.6, caption=None, header_fill=NAVY_HEX,
          status_col=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for j, head in enumerate(headers):
        cell = t.rows[0].cells[j]
        shade(cell, header_fill)
        no_borders(cell)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
        run(p, head, size=size - 0.4, bold=True, colour=RGBColor(0xFF, 0xFF, 0xFF))
    for i, row in enumerate(rows):
        cells = t.add_row().cells
        for j, value in enumerate(row):
            cell = cells[j]
            cell_borders(cell, colour="E8ECF3", sz=4)
            if i % 2 == 1:
                shade(cell, BAND)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(2.5)
            p.paragraph_format.space_after = Pt(2.5)
            p.paragraph_format.line_spacing = 1.06
            text = "" if value is None else str(value)
            colour = INK
            bold = j == 0
            if status_col is not None and j == status_col:
                if text.lower().startswith("pass"):
                    colour, bold = GREEN, True
                elif text.lower().startswith("fail"):
                    colour, bold = ROSE, True
            run(p, text, size=size, bold=bold, colour=colour if not bold else colour)
    if widths:
        total = sum(widths)
        for row in t.rows:
            for j, cell in enumerate(row.cells):
                cell.width = Cm(16.4 * widths[j] / total)
    if caption:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(10)
        run(p, caption, size=7.8, italic=True, colour=INK3)
    else:
        spacer(doc, 8)
    return t


def kpi_strip(doc, items):
    table = doc.add_table(rows=1, cols=len(items))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    fills = {"green": GREEN_HEX, "amber": AMBER_HEX, "rose": ROSE_HEX, "teal": TINT_TEAL,
             "navy": TINT_NAVY}
    colours = {"green": GREEN, "amber": AMBER, "rose": ROSE, "teal": TEAL, "navy": NAVY}
    for j, (value, label, tone) in enumerate(items):
        cell = table.cell(0, j)
        shade(cell, fills.get(tone, BAND))
        cell_borders(cell, colour=RULE)
        cell.width = Cm(16.4 / len(items))
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(0)
        run(p, str(value), size=17, bold=True, colour=colours.get(tone, NAVY), font=DISPLAY)
        p2 = cell.add_paragraph()
        p2.paragraph_format.space_after = Pt(5)
        run(p2, label, size=7.6, colour=INK3)
    spacer(doc, 10)


def figure(doc, path: Path, caption: str, width_cm=15.6):
    if not path.exists():
        return
    doc.add_picture(str(path), width=Cm(width_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(10)
    run(p, caption, size=7.8, italic=True, colour=INK3)


def code_block(doc, text):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.cell(0, 0)
    cell.width = Cm(16.4)
    shade(cell, "1E2430")
    no_borders(cell)
    for i, line in enumerate(text.split("\n")):
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        run(p, line if line else " ", size=8, colour=RGBColor(0xE7, 0xED, 0xF5), font=MONO)
    spacer(doc, 8)


# ----------------------------------------------------------------- data
def load(name):
    path = QA / name
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def suite_totals():
    pytest_log = QA / "pytest_output.txt"
    total = passed = failed = 0
    if pytest_log.exists():
        text = pytest_log.read_text()
        m = re.search(r"(\d+) passed", text)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+) failed", text)
        failed = int(m.group(1)) if m else 0
        total = passed + failed
    return {"total": total, "passed": passed, "failed": failed}


def fix_log():
    path = QA / "fixes.json"
    return json.loads(path.read_text()) if path.exists() else []
