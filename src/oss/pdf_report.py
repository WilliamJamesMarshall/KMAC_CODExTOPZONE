"""Build a Korean report from the current screen's content, entirely in memory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import re
from threading import Lock
from xml.sax.saxutils import escape
from urllib.parse import urlparse

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
    "representative", "homepage_url", "specialization", "description", "coverage_note",
)
_ENCLOSED_NUMBERS = {0x2460 + index: str(index + 1) for index in range(20)}
_ENCLOSED_NUMBERS[0x24EA] = "0"


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


def validate_failure_report(payload: dict) -> dict:
    fields = ("source_url", "started_at", "failed_at", "stage", "code", "message",
              "action", "revision", "request_url", "http_status", "partial_business_summary")
    report = {key: _text(payload.get(key, "")) for key in fields}
    parsed = urlparse(report["source_url"])
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(not report[key] for key in ("stage", "code", "message", "failed_at"))):
        raise ValueError("실패 진단 보고서의 필수 항목이 올바르지 않습니다.")
    if not re.fullmatch(r"[a-z_]{1,80}", report["code"]):
        raise ValueError("실패 진단 코드가 올바르지 않습니다.")
    report.update(kind="analysis_failure", company_name=parsed.hostname)
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
    # Nanum lacks the legacy halfwidth circle and subscript digit glyphs.
    # Preserve their appearance using supported circle text and real subscript markup.
    # Preserve the values of enclosed list numbers missing from the Korean font.
    value = text.translate(_ENCLOSED_NUMBERS).replace("\uffee", "\u25cb").replace("❍", "○")
    primary = pdfmetrics.getFont(style.fontName).face.charToGlyph
    fallback = pdfmetrics.getFont("OSS-CJK-Fallback").face.charToGlyph
    markup = "".join(
        '<font name="OSS-CJK-Fallback">' + escape(char) + '</font>'
        if ord(char) not in primary and ord(char) in fallback else escape(char)
        for char in value).replace("\n", "<br/>")
    for digit, character in enumerate("₀₁₂₃₄₅₆₇₈₉"):
        markup = markup.replace(character, f"<sub>{digit}</sub>")
    return Paragraph(markup, style)


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
            if supplier["coverage_note"]:
                add(supplier["coverage_note"], "body")
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
            if number < len(work["suppliers"]):
                story.append(Spacer(1, 6 * mm))
    return story


def _page(canvas, document) -> None:
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(HexColor("#365fc9"))
    canvas.setFont("OSS-Nanum-Bold", 9)
    failed = getattr(document, "report_kind", None) == "analysis_failure"
    canvas.drawString(20 * mm, height - 15 * mm,
                      "OSS  /  ANALYSIS FAILURE RECORD" if failed else "OSS  /  AX MATCHING REPORT")
    canvas.setStrokeColor(HexColor("#dce3f0"))
    canvas.line(20 * mm, 17 * mm, width - 20 * mm, 17 * mm)
    canvas.setFillColor(HexColor("#778398"))
    canvas.setFont("OSS-Nanum", 8)
    canvas.drawString(20 * mm, 11 * mm, "분석 실패 진단 기록" if failed else "AX 활용 업무 및 공급기업 분석")
    canvas.drawRightString(width - 20 * mm, 11 * mm, str(document.page))
    canvas.restoreState()


def build_report(payload: object, *, created_at: datetime | None = None) -> tuple[bytes, str]:
    """Return PDF bytes and a safe download filename; do not save or reanalyze."""
    failed = isinstance(payload, dict) and payload.get("kind") == "analysis_failure"
    report = validate_failure_report(payload) if failed else validate_report(payload)
    stamp = (created_at or datetime.now(KST)).astimezone(KST)
    company = re.sub(r'[^\w가-힣 .()-]', "_", report["company_name"])[:70].strip(" .") or "기업"
    label = "분석실패_진단보고서" if failed else "AX분석보고서"
    filename = f"{company}_{label}_{stamp:%Y%m%d}.pdf"
    buffer = BytesIO()
    with _PDF_LOCK:
        if "OSS-Nanum" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("OSS-Nanum", str(FONT_DIR / "NanumGothic-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("OSS-Nanum-Bold", str(FONT_DIR / "NanumGothic-Bold.ttf")))
        if "OSS-CJK-Fallback" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("OSS-CJK-Fallback", str(FONT_DIR / "OSSFallbackCJK-Regular.ttf")))
        document = SimpleDocTemplate(
            buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
            topMargin=25 * mm, bottomMargin=24 * mm,
            title=report["company_name"] + " " + label, author="OSS",
        )
        document.report_kind = report.get("kind")
        if failed:
            styles = _styles()
            story = [_paragraph("분석 실패 진단 기록", styles["title"]),
                     _paragraph("기업 분석 결과를 생성하지 못했습니다. 아래 내용은 수집·처리 실패에 관한 진단 기록입니다.", styles["body"])]
            labels = {"source_url": "입력 홈페이지", "started_at": "분석 시작 시각",
                      "failed_at": "실패 확인 시각", "stage": "처리 단계", "code": "오류 코드",
                      "message": "확인된 오류", "request_url": "오류 발생 요청 주소",
                      "http_status": "HTTP 응답", "action": "다음 확인사항", "revision": "앱 버전",
                      "partial_business_summary": "실패 전 확인된 기업 이해 (부분 결과)"}
            for key, heading in labels.items():
                if report[key]:
                    story.extend([_paragraph(heading, styles["label"]),
                                  _paragraph(report[key], styles["body"])])
        else:
            story = _story(report, stamp)
        document.build(story, onFirstPage=_page, onLaterPages=_page)
    return buffer.getvalue(), filename
