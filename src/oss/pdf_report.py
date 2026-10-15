"""Build a Korean report from the current screen's content, entirely in memory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import re
from threading import Lock
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer


KST = timezone(timedelta(hours=9))
FONT_DIR = Path(__file__).with_name("fonts")
# ReportLab TTFont instances must not be shared by simultaneous document builds.
_PDF_LOCK = Lock()
WORK_FIELDS = ("title", "mechanism", "process_change", "check")
SUPPLIER_FIELDS = (
    "name", "solution_name", "why", "how", "change", "check", "phone", "address",
    "representative", "homepage_url", "specialization", "description",
)


def _text(value: object) -> str:
    if not isinstance(value, str) or len(value) > 30000:
        raise ValueError("보고서 항목은 30,000자 이내의 텍스트여야 합니다.")
    return "".join(char for char in value if char.isprintable() or char in "\n\t").strip()


def validate_report(payload: object) -> dict:
    """Accept only display fields, with the same three-work/three-supplier limits."""
    if not isinstance(payload, dict):
        raise ValueError("보고서 데이터가 올바르지 않습니다.")
    report = {key: _text(payload.get(key, "")) for key in
              ("company_name", "source_url", "business_summary")}
    if not report["company_name"] or not report["business_summary"]:
        raise ValueError("보고서를 만들 분석 결과가 없습니다.")
    works = payload.get("works")
    if not isinstance(works, list) or len(works) > 3:
        raise ValueError("보고서에는 최대 3개의 추천 업무를 담을 수 있습니다.")
    report["is_demo"] = payload.get("is_demo") is True
    report["works"] = []
    for item in works:
        if not isinstance(item, dict):
            raise ValueError("추천 업무 데이터가 올바르지 않습니다.")
        work = {key: _text(item.get(key, "")) for key in WORK_FIELDS}
        if not work["title"]:
            raise ValueError("추천 업무명이 없습니다.")
        suppliers = item.get("suppliers")
        if not isinstance(suppliers, list) or len(suppliers) > 3:
            raise ValueError("업무별 공급기업은 최대 3곳이어야 합니다.")
        work["suppliers"] = []
        for supplier in suppliers:
            if not isinstance(supplier, dict):
                raise ValueError("공급기업 데이터가 올바르지 않습니다.")
            row = {key: _text(supplier.get(key, "")) for key in SUPPLIER_FIELDS}
            if not row["name"]:
                raise ValueError("공급기업명이 없습니다.")
            work["suppliers"].append(row)
        report["works"].append(work)
    return report


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "body", fontName="OSS-Nanum", fontSize=10.5, leading=17,
        textColor=HexColor("#344156"), wordWrap="CJK", spaceAfter=10,
    )
    return {
        "body": base,
        "title": ParagraphStyle("title", parent=base, fontName="OSS-Nanum-Bold",
                                fontSize=25, leading=34, textColor=HexColor("#243763"),
                                spaceAfter=12),
        "subtitle": ParagraphStyle("subtitle", parent=base, fontSize=15, leading=23,
                                   spaceAfter=20),
        "section": ParagraphStyle("section", parent=base, fontName="OSS-Nanum-Bold",
                                  fontSize=17, leading=25, textColor=HexColor("#365fc9"),
                                  spaceBefore=18, spaceAfter=14, keepWithNext=True),
        "supplier": ParagraphStyle("supplier", parent=base, fontName="OSS-Nanum-Bold",
                                   fontSize=14, leading=21, textColor=HexColor("#243763"),
                                   spaceBefore=18, spaceAfter=10, keepWithNext=True),
        "label": ParagraphStyle("label", parent=base, fontName="OSS-Nanum-Bold",
                                fontSize=10, leading=16, spaceBefore=5, spaceAfter=4,
                                keepWithNext=True),
        "small": ParagraphStyle("small", parent=base, fontSize=9, leading=15,
                                textColor=HexColor("#66738a"), spaceAfter=7),
    }


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _story(report: dict, stamp: datetime) -> list:
    styles = _styles()
    story = []

    def add(text: str, kind: str = "body") -> None:
        story.append(_paragraph(text, styles[kind]))

    def answer(label: str, text: str) -> None:
        if text:
            add(label, "label")
            add(text)

    add(report["company_name"], "title")
    add("AX 활용 업무 및 공급기업 분석 보고서", "subtitle")
    add("분석 대상: " + (report["source_url"] or "미입력"), "small")
    add("보고서 생성: " + stamp.strftime("%Y.%m.%d %H:%M") + " (한국시간)", "small")
    if report["is_demo"]:
        add("화면 예시 · 가상 수요기업", "small")
    story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor("#4c71d5")))
    add("01  기업 이해", "section")
    add(report["business_summary"])
    add("02  추천 업무 한눈에 보기", "section")
    if not report["works"]:
        add("홈페이지 정보에서 추천할 활용 업무를 찾지 못했습니다.")
    for index, work in enumerate(report["works"], 1):
        add(f"{index}. {work['title']}", "label")
        add(f"관련 공급기업 {len(work['suppliers'])}곳", "small")

    for index, work in enumerate(report["works"], 1):
        story.append(PageBreak())
        add(f"02-{index}  {work['title']}", "section")
        answer("무엇을 도와주나요?", work["mechanism"])
        answer("어떤 점이 좋아지나요?", work["process_change"])
        answer("도입 전 확인할 점", work["check"])
        add("추천 공급기업", "section")
        if not work["suppliers"]:
            add("이 업무에 연결된 업체가 아직 없습니다.")
        for number, supplier in enumerate(work["suppliers"], 1):
            add(f"{number}. {supplier['name']}", "supplier")
            if supplier["solution_name"]:
                add(supplier["solution_name"], "small")
            for label, key in (("왜 이 업체인가요?", "why"),
                               ("우리 업무에 어떻게 쓰나요?", "how"),
                               ("업무가 어떻게 달라지나요?", "change"),
                               ("상담할 때 무엇을 확인하나요?", "check")):
                answer(label, supplier[key])
            add("상담·문의", "label")
            for label, key in (("전화번호", "phone"), ("주소", "address"),
                               ("대표자명", "representative"), ("홈페이지", "homepage_url")):
                add(f"{label}: {supplier[key] or '등록된 정보가 없습니다.'}", "small")
            if supplier["description"]:
                add("상세정보", "label")
                if supplier["specialization"]:
                    add("전문분야: " + supplier["specialization"], "small")
                add(supplier["description"], "small")
            story.append(Spacer(1, 6 * mm))
    return story


def _page(canvas, document) -> None:
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(HexColor("#365fc9"))
    canvas.setFont("OSS-Nanum-Bold", 9)
    canvas.drawString(20 * mm, height - 15 * mm, "OSS  /  AX MATCHING REPORT")
    canvas.setStrokeColor(HexColor("#dce3f0"))
    canvas.line(20 * mm, 17 * mm, width - 20 * mm, 17 * mm)
    canvas.setFillColor(HexColor("#778398"))
    canvas.setFont("OSS-Nanum", 8)
    canvas.drawString(20 * mm, 11 * mm, "AX 활용 업무 및 공급기업 분석")
    canvas.drawRightString(width - 20 * mm, 11 * mm, str(document.page))
    canvas.restoreState()


def build_report(payload: object, *, created_at: datetime | None = None) -> tuple[bytes, str]:
    """Return PDF bytes and a safe download filename; do not save or reanalyze."""
    report = validate_report(payload)
    stamp = (created_at or datetime.now(KST)).astimezone(KST)
    company = re.sub(r'[^\w가-힣 .()-]', "_", report["company_name"])[:70].strip(" .") or "기업"
    filename = f"{company}_AX분석보고서_{stamp:%Y%m%d}.pdf"
    buffer = BytesIO()
    with _PDF_LOCK:
        if "OSS-Nanum" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("OSS-Nanum", str(FONT_DIR / "NanumGothic-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("OSS-Nanum-Bold", str(FONT_DIR / "NanumGothic-Bold.ttf")))
        document = SimpleDocTemplate(
            buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
            topMargin=25 * mm, bottomMargin=24 * mm,
            title=report["company_name"] + " AX 분석 보고서", author="OSS",
        )
        document.build(_story(report, stamp), onFirstPage=_page, onLaterPages=_page)
    return buffer.getvalue(), filename
