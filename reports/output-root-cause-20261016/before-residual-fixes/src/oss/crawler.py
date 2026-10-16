"""Small, bounded crawler for public company pages."""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from contextlib import ExitStack
from html.parser import HTMLParser
from http.client import InvalidURL
from typing import Callable
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from .models import WebPage


USER_AGENT = "OSS-AX-Research/0.1 (+public company page analysis)"
MAX_BYTES = 3_000_000
PAGE_HINTS = (
    "solution", "product", "service", "case", "portfolio", "project", "company", "about",
    "business", "technology", "research", "rnd", "r&d", "production", "manufacturing",
    "factory", "quality", "certification", "oem", "odm", "partner", "client", "recruit",
    "health", "veterinary", "labanimal", "실험동물",
    "사업", "제품", "서비스", "사례", "솔루션", "구축", "포트폴리오", "프로젝트",
    "회사소개", "연구", "기술", "생산", "제조", "공장", "품질", "인증", "고객", "채용",
)
PAGE_PRIORITY = (
    ("company", "about", "회사소개", "인사말"),
    ("business", "service", "사업", "서비스"),
    ("research", "rnd", "r&d", "technology", "연구", "기술"),
    ("production", "manufacturing", "factory", "생산", "제조", "공장"),
    ("quality", "certification", "품질", "인증"),
    ("product", "solution", "제품", "솔루션"),
    ("oem", "odm", "partner", "client", "고객"),
    ("case", "portfolio", "project", "사례", "구축", "포트폴리오"),
    ("news", "recruit", "보도", "채용"),
)


def _public_http_url(url: str) -> str:
    if any(ord(char) <= 32 for char in url):
        raise ValueError("URL contains whitespace or control characters")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) URLs are allowed")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Nonstandard URL ports are not allowed")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as error:
        raise CrawlError("Website hostname could not be resolved", code="dns_failed") from error
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("Private or local network addresses are not allowed")
    return url


def diagnostic_url(url: str) -> str:
    """Keep paths useful for diagnosis without credentials or query values."""
    try:
        parsed = urlparse(url)
        return parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[-1], query="", fragment="").geturl()
    except ValueError:
        return "<invalid URL>"


def _same_site_host(host: str | None, other: str | None) -> bool:
    return bool(host and other and host.removeprefix("www.") == other.removeprefix("www."))


class CrawlError(RuntimeError):
    code = "fetch_failed"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class _SameHostRedirects(HTTPRedirectHandler):
    def __init__(self, host: str, *, check_page=None, diagnostics: dict | None = None,
                 request_kind: str = "page") -> None:
        self.host = host
        self.check_page = check_page
        self.diagnostics = diagnostics
        self.request_kind = request_kind

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if self.diagnostics is not None:
            self.diagnostics.setdefault("redirects", []).append({
                "from": diagnostic_url(request.full_url), "to": diagnostic_url(newurl),
                "http_status": code, "request_kind": self.request_kind,
            })
        try:
            _public_http_url(newurl)
        except ValueError as error:
            raise CrawlError("Unsafe redirect blocked", code="redirect_blocked") from error
        if not _same_site_host(self.host, urlparse(newurl).hostname):
            raise CrawlError("Cross-host redirect blocked", code="redirect_blocked")
        if self.check_page:
            self.check_page(newurl)
        if self.diagnostics is not None:
            self.diagnostics.update(request_url=diagnostic_url(newurl), request_kind=self.request_kind)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class RobotsDisallowed(CrawlError):
    """The site explicitly prohibits fetching the requested page."""
    code = "robots_disallowed"


class RateLimited(CrawlError):
    """The site requested that automated access stop."""
    code = "rate_limited"


class _SiteAccess:
    """Check each origin's robots policy before fetching any page on it."""

    def __init__(self, host: str, diagnostics: dict | None) -> None:
        self.host = host
        self.diagnostics = diagnostics
        self.policies: dict[str, RobotFileParser] = {}
        self.delay = 1

    def mark(self, url: str, kind: str) -> None:
        if self.diagnostics is not None:
            self.diagnostics.update(request_url=diagnostic_url(url), request_kind=kind)
            self.diagnostics.pop("http_status", None)

    def check_page(self, url: str) -> RobotFileParser:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.policies:
            robots_url = origin + "/robots.txt"
            self.mark(robots_url, "robots")
            opener = build_opener(_SameHostRedirects(
                self.host, diagnostics=self.diagnostics, request_kind="robots",
            ))
            robots = RobotFileParser()
            try:
                with opener.open(Request(robots_url, headers={"User-Agent": USER_AGENT}), timeout=12) as response:
                    if self.diagnostics is not None:
                        self.diagnostics["http_status"] = response.status
                    raw = response.read(200_001)
                    text = raw.decode("utf-8", errors="replace")
                    if len(raw) > 200_000 or re.search(r"<\s*(?:!doctype|html)\b", text[:500], re.IGNORECASE):
                        raise CrawlError("Invalid robots.txt response", code="robots_unavailable")
                    robots.parse(text.splitlines())
            except HTTPError as error:
                if self.diagnostics is not None:
                    self.diagnostics["http_status"] = error.code
                if error.code == 429:
                    raise RateLimited("Website returned HTTP 429 for robots.txt") from error
                if error.code != 404:
                    code = "redirect_loop" if 300 <= error.code < 400 else "robots_unavailable"
                    raise CrawlError("Could not read robots.txt", code=code) from error
                robots.parse([])
            except TimeoutError as error:
                raise CrawlError("robots.txt request timed out", code="fetch_timeout") from error
            except URLError as error:
                code = "fetch_timeout" if isinstance(error.reason, TimeoutError) else "robots_unavailable"
                raise CrawlError("Could not connect to robots.txt", code=code) from error
            except (OSError, ValueError) as error:
                raise CrawlError("Could not read robots.txt", code="robots_unavailable") from error
            self.policies[origin] = robots
        robots = self.policies[origin]
        if not robots.can_fetch(USER_AGENT, url):
            self.mark(url, "page")
            raise RobotsDisallowed("robots.txt disallows page")
        if (robots.crawl_delay(USER_AGENT) or 0) > 10:
            raise CrawlError("Crawl delay exceeds pilot limit", code="crawl_delay_exceeded")
        self.delay = max(self.delay, robots.crawl_delay(USER_AGENT) or 0)
        self.mark(url, "page")
        return robots


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._ignored = 0
        self._title = False
        self._capture = 0
        self._buffer: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        self._body = False
        self._visible_buffer: list[str] = []
        self.visible_parts: list[str] = []

    def _flush_visible(self) -> None:
        value = re.sub(r"\s+", " ", " ".join(self._visible_buffer)).strip()
        if value:
            self.visible_parts.append(value)
        self._visible_buffer = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a":
            self._href = attributes.get("href")
            self._link_text = []
        if tag in {"script", "style", "nav", "footer", "header", "noscript"}:
            self._ignored += 1
        if self._ignored:
            return
        if tag == "body":
            self._body = True
        if self._body and tag in {"div", "section", "article", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br"}:
            self._flush_visible()
        if tag == "title":
            self._title = True
        if tag in {"p", "li", "h1", "h2", "h3", "h4"}:
            self._capture += 1
            if self._capture == 1:
                self._buffer = []
    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, "".join(self._link_text).strip()))
            self._href = None
        if tag in {"script", "style", "nav", "footer", "header", "noscript"} and self._ignored:
            self._ignored -= 1
            return
        if self._ignored:
            return
        if self._body and tag in {"div", "section", "article", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "body"}:
            self._flush_visible()
        if tag == "body":
            self._body = False
        if tag == "title":
            self._title = False
        if tag in {"p", "li", "h1", "h2", "h3", "h4"} and self._capture:
            self._capture -= 1
            if self._capture == 0:
                value = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
                if value:
                    self.parts.append(value)
    def handle_data(self, data: str) -> None:
        if self._href:
            self._link_text.append(data)
        if self._ignored:
            return
        if self._title:
            self.title += data
        if self._body:
            self._visible_buffer.append(data)
        if self._capture:
            self._buffer.append(data)


def extract_html(url: str, html: str) -> tuple[WebPage, list[tuple[str, str]]]:
    parser = _Extractor()
    parser.feed(html)
    parser._flush_visible()
    # Captured headings must not suppress business copy in adjacent divs/sections.
    text = "\n".join(dict.fromkeys(parser.visible_parts or parser.parts))
    return WebPage(url, re.sub(r"\s+", " ", parser.title).strip(), text), parser.links


def has_readable_content(page: WebPage) -> bool:
    lines = [line.strip() for line in page.text.splitlines() if line.strip()]
    substantive = [line for line in lines if line != page.title and not re.fullmatch(
        r"loading[.\s]*|로딩\s*중[.\s]*|to\s*top|top|menu|메뉴", line, re.I)]
    return bool(substantive) and len("".join(substantive)) >= 20


def decode_html(raw: bytes, charset: str | None) -> str:
    """Honor legacy HTML charset declarations when HTTP does not specify one."""
    declared = re.search(rb'<meta\b[^>]*charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', raw[:8192], re.I)
    encoding = charset or (declared.group(1).decode('ascii') if declared else 'utf-8')
    try:
        return raw.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return raw.decode('utf-8', errors='replace')


def _link_priority(value: str) -> int:
    value = value.lower()
    return next((index for index, hints in enumerate(PAGE_PRIORITY) if any(hint in value for hint in hints)), 4)


def _crawl_bucket(priority: int, url: str) -> str:
    path = urlparse(url).path.lower()
    for prefix in ("/products/human", "/products/veterinary", "/products/health", "/labanimal/"):
        if path.startswith(prefix):
            return prefix
    return str(priority)


def crawl_site(
    url: str, max_pages: int = 6, *, on_page: Callable[[str, bytes], None] | None = None,
    diagnostics: dict | None = None,
) -> list[WebPage]:
    with ExitStack() as resources:
        return _crawl_site(url, max_pages, on_page=on_page, diagnostics=diagnostics, resources=resources)


def _crawl_site(url: str, max_pages: int, *, on_page, diagnostics, resources: ExitStack) -> list[WebPage]:
    """Fetch public pages, allowing exact www aliases and checking robots per origin."""
    if not 1 <= max_pages <= 20:
        raise ValueError("max_pages must be between 1 and 20")
    homepage = _public_http_url(url)
    host = urlparse(homepage).hostname
    access = _SiteAccess(host, diagnostics)
    redirects = _SameHostRedirects(host, check_page=access.check_page, diagnostics=diagnostics)
    opener = build_opener(redirects)
    pending = [(-1, homepage)]
    scheduled = {homepage}
    visited: set[str] = set()
    type_counts: dict[str, int] = {}
    pages: list[WebPage] = []
    renderer = None
    while pending and len(pages) < max_pages:
        pending.sort(key=lambda item: (
            item[0] >= 8, type_counts.get(_crawl_bucket(*item), 0), item[0],
            bool(urlparse(item[1]).query),
        ))
        priority, current = pending.pop(0)
        current, _ = urldefrag(current)
        if current in visited:
            continue
        visited.add(current)
        _public_http_url(current)
        if not _same_site_host(host, urlparse(current).hostname):
            continue
        try:
            access.check_page(current)
        except RobotsDisallowed:
            if not pages:
                raise
            continue
        delay = access.delay
        request = Request(current, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        try:
            if pages and delay:
                time.sleep(delay)
            with opener.open(request, timeout=12) as response:
                final_url = _public_http_url(response.url)
                if diagnostics is not None:
                    diagnostics["http_status"] = response.status
                if not _same_site_host(host, urlparse(final_url).hostname):
                    continue
                if not pages and diagnostics is not None:
                    diagnostics["canonical_url"] = diagnostic_url(final_url)
                if "text/html" not in response.headers.get("Content-Type", ""):
                    continue
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    continue
                charset = response.headers.get_content_charset()
        except HTTPError as error:
            if diagnostics is not None:
                diagnostics["http_status"] = error.code
            if error.code == 429:
                raise RateLimited("Website returned HTTP 429") from error
            if not pages:
                code = "redirect_loop" if 300 <= error.code < 400 else "fetch_failed"
                raise CrawlError("Homepage request failed", code=code) from error
            continue
        except CrawlError as error:
            # A linked news article leaving the site must not discard internal pages.
            if pages and error.code == "redirect_blocked":
                if diagnostics is not None:
                    diagnostics.setdefault("skipped_pages", []).append({
                        "url": diagnostic_url(current), "reason": error.code})
                continue
            raise
        except TimeoutError as error:
            if not pages:
                raise CrawlError("Homepage request timed out", code="fetch_timeout") from error
            continue
        except URLError as error:
            if not pages:
                code = "fetch_timeout" if isinstance(error.reason, TimeoutError) else "fetch_failed"
                raise CrawlError("Homepage connection failed", code=code) from error
            continue
        except (OSError, UnicodeError, ValueError, InvalidURL):
            if not pages:
                raise CrawlError("Homepage connection failed")
            continue
        if on_page:
            on_page(final_url, raw)
        decoded = decode_html(raw, charset)
        page, links = extract_html(final_url, decoded)
        refresh = re.search(r'<meta\b[^>]*http-equiv\s*=\s*["\']?refresh["\']?[^>]*>', decoded, re.I)
        if refresh:
            destination = re.search(r'url\s*=\s*([^"\'<>]+)', refresh.group(), re.I)
            if destination:
                target = urljoin(final_url, destination.group(1).strip())
                _public_http_url(target)
                if not _same_site_host(host, urlparse(target).hostname):
                    if not pages:
                        raise CrawlError("Cross-host page refresh blocked", code="redirect_blocked")
                elif target not in scheduled and len(visited) < 30:
                    scheduled.add(target)
                    pending.append((-1, target))
                if not has_readable_content(page):
                    continue
        if not has_readable_content(page) and re.search(r"<script\b", decoded, re.IGNORECASE):
            if renderer is None:
                from .browser_render import BrowserRenderer
                renderer = resources.enter_context(BrowserRenderer(access, diagnostics))
            try:
                final_url, rendered = renderer.render(final_url, decoded)
            except CrawlError as error:
                if pages and error.code == "render_failed":
                    continue
                if pages and error.code == "render_limit":
                    break
                raise
            page, links = extract_html(final_url, rendered)
        visited.add(final_url)
        scheduled.add(final_url)
        if has_readable_content(page):
            pages.append(page)
            bucket = _crawl_bucket(priority, current)
            type_counts[bucket] = type_counts.get(bucket, 0) + 1
        candidates: list[tuple[int, str]] = []
        for href, label in links:
            try:
                target, _ = urldefrag(urljoin(final_url, href))
                parsed = urlparse(target)
            except ValueError:
                continue
            if any(ord(char) <= 32 for char in target):
                continue
            if not _same_site_host(host, parsed.hostname) or parsed.scheme not in {"http", "https"}:
                continue
            if target in scheduled:
                continue
            if any(hint in (parsed.path + " " + label).lower() for hint in PAGE_HINTS):
                candidates.append((_link_priority(parsed.path + " " + label), target))
                scheduled.add(target)
        pending.extend(candidates)
    if not pages:
        raise CrawlError("No readable homepage content", code="no_content")
    return pages
