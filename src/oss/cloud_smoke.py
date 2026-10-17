"""Offline browser and Korean font checks, runnable inside the deployment image."""

from playwright.sync_api import sync_playwright

from .pdf_report import build_report


def main():
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content("<html><body><script>document.body.textContent = 'Chromium ready';</script></body></html>")
            assert page.locator("body").inner_text() == "Chromium ready"
        finally:
            browser.close()
    pdf, filename = build_report({"company_name": "배포 점검", "source_url": "https://example.com/",
                                  "business_summary": "한글 보고서 점검입니다.", "works": []})
    if not pdf.startswith(b"%PDF-") or not filename.endswith(".pdf"):
        raise RuntimeError("PDF smoke check failed")
    print("Chromium JavaScript and Korean PDF checks passed; no external API was called.")


if __name__ == "__main__":
    main()
