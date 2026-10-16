"""Render empty JavaScript shells using bounded, crawler-controlled requests."""

from __future__ import annotations

import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

from .crawler import (CrawlError, MAX_BYTES, RateLimited, USER_AGENT, _public_http_url,
                      _same_site_host, _SameHostRedirects, diagnostic_url)


class BrowserRenderer:
    def __init__(self, access, diagnostics: dict | None) -> None:
        self.access = access
        self.diagnostics = diagnostics
        self.runtime = self.browser = None
        self.cache: dict[str, tuple[str, bytes]] = {}
        self.total_bytes = 0

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
            self.runtime = sync_playwright().start()
            # Use bundled Chromium in deployments; installed Chrome/Edge work locally.
            for options in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
                try:
                    self.browser = self.runtime.chromium.launch(headless=True, **options)
                    break
                except Exception:
                    continue
            if self.browser is None:
                raise RuntimeError("No supported browser installed")
            return self
        except Exception as error:
            self.__exit__(None, None, None)
            raise CrawlError("Browser rendering is unavailable", code="render_unavailable") from error

    def __exit__(self, *args):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self.runtime:
                self.runtime.stop()

    def render(self, url: str, html: str) -> tuple[str, str]:
        from playwright.sync_api import Error, TimeoutError as BrowserTimeout

        started = time.monotonic()
        failures = []
        requests = 0
        completed = False
        context = self.browser.new_context(service_workers="block", accept_downloads=False,
                                           user_agent=USER_AGENT, offline=True)
        context.route_web_socket("**/*", lambda connection: connection.close())
        page = context.new_page()
        page.on("popup", lambda popup: popup.close())

        def handle(route):
            nonlocal requests
            request = route.request
            if (request.method != "GET" or request.resource_type not in
                    {"document", "script", "stylesheet", "fetch", "xhr"}
                    or request.frame != page.main_frame
                    or not _same_site_host(self.access.host, urlparse(request.url).hostname)):
                if self.diagnostics is not None:
                    self.diagnostics.setdefault("blocked_resources", []).append({
                        "url": diagnostic_url(request.url), "type": request.resource_type,
                        "reason": "method_type_frame_or_host"})
                if request.resource_type == "document" and request.frame == page.main_frame:
                    failures.append(CrawlError("Rendered page left the website", code="redirect_blocked"))
                route.abort()
                return
            try:
                remaining = 25 - (time.monotonic() - started)
                requests += 1
                if remaining <= 0 or requests > 60 or self.total_bytes > 20_000_000:
                    raise CrawlError("Rendering resource limit reached", code="render_limit")
                _public_http_url(request.url)
                if request.url == url and request.resource_type == "document":
                    content_type, body = "text/html; charset=utf-8", html.encode("utf-8")
                elif request.url in self.cache:
                    content_type, body = self.cache[request.url]
                else:
                    self.access.check_page(request.url)
                    self.access.mark(request.url, "render_resource")
                    if request.resource_type == "document":
                        time.sleep(self.access.delay)
                    opener = build_opener(_SameHostRedirects(
                        self.access.host, check_page=self.access.check_page,
                        diagnostics=self.diagnostics, request_kind="render_resource",
                    ))
                    with opener.open(Request(request.url, headers={"User-Agent": USER_AGENT}),
                                     timeout=min(12, remaining)) as response:
                        body = response.read(MAX_BYTES + 1)
                        content_type = response.headers.get("Content-Type", "application/octet-stream")
                    if len(body) > MAX_BYTES:
                        raise CrawlError("Rendering resource is too large", code="render_limit")
                    self.total_bytes += len(body)
                    if self.total_bytes > 20_000_000:
                        raise CrawlError("Rendering byte budget exceeded", code="render_limit")
                    if request.resource_type in {"script", "stylesheet"}:
                        self.cache[request.url] = (content_type, body)
                # Browser has no direct network access; only these validated bytes are served.
                route.fulfill(status=200, content_type=content_type, body=body)
            except HTTPError as error:
                if self.diagnostics is not None:
                    self.diagnostics["http_status"] = error.code
                if error.code == 429:
                    failures.append(RateLimited("Website limited rendering requests"))
                route.abort()
            except CrawlError as error:
                failures.append(error)
                route.abort()
            except (OSError, ValueError):
                route.abort()

        context.route("**/*", handle)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            if failures:
                raise failures[0]
            # Wait for actual content, rather than assuming the page-load event means hydration ended.
            page.wait_for_function(r"""() => {
                if (!document.body) return false;
                const copy = document.body.cloneNode(true);
                copy.querySelectorAll('script,style,nav,footer,header,noscript').forEach(x => x.remove());
                const text = copy.textContent.replace(/loading[.\s]*|로딩\s*중[.\s]*|to\s*top/ig, '').trim();
                return text.length >= 20;
            }""", timeout=max(1, 25_000 - (time.monotonic() - started) * 1000))
            if failures:
                raise failures[0]
            rendered = page.content()
            if len(rendered.encode("utf-8")) > MAX_BYTES:
                raise CrawlError("Rendered document is too large", code="render_limit")
            final_url = _public_http_url(page.url)
            if not _same_site_host(self.access.host, urlparse(final_url).hostname):
                raise CrawlError("Rendered page left the website", code="redirect_blocked")
            completed = True
            return final_url, rendered
        except (BrowserTimeout, Error) as error:
            if self.diagnostics is not None:
                self.diagnostics["render_exception"] = {"type": type(error).__name__,
                    "message": str(error).splitlines()[0][:300]}
            if failures:
                raise failures[0] from error
            raise CrawlError("JavaScript did not produce readable content", code="render_failed") from error
        finally:
            if self.diagnostics is not None:
                self.diagnostics.setdefault("rendering", []).append({
                    "url": diagnostic_url(url), "requests": requests,
                    "status": "completed" if completed else "failed",
                    "duration_seconds": round(time.monotonic() - started, 3),
                })
            context.close()
