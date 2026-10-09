"""Small, bounded crawler for public company pages."""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from html.parser import HTMLParser
from http.client import InvalidURL
from typing import Callable
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.error import HTTPError
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
    for address in {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("Private or local network addresses are not allowed")
    return url


class _SameHostRedirects(HTTPRedirectHandler):
    def __init__(self, host: str) -> None:
        self.host = host
        self.robots: RobotFileParser | None = None

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        _public_http_url(newurl)
        if urlparse(newurl).hostname != self.host:
            raise ValueError("Cross-host redirect blocked")
        if self.robots and not self.robots.can_fetch(USER_AGENT, newurl):
            raise RobotsDisallowed("robots.txt disallows redirected page")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class RobotsDisallowed(RuntimeError):
    """The site explicitly prohibits fetching the requested page."""


class RateLimited(RuntimeError):
    """The site requested that automated access stop."""


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
    text = "\n".join(dict.fromkeys(parser.parts or parser.visible_parts))
    return WebPage(url, re.sub(r"\s+", " ", parser.title).strip(), text), parser.links


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
) -> list[WebPage]:
    """Fetch a few same-host pages, respecting robots.txt and byte/page caps."""
    if not 1 <= max_pages <= 20:
        raise ValueError("max_pages must be between 1 and 20")
    homepage = _public_http_url(url)
    host = urlparse(homepage).hostname
    redirects = _SameHostRedirects(host)
    opener = build_opener(redirects)
    robots = RobotFileParser()
    robots_url = urljoin(homepage, "/robots.txt")
    try:
        with opener.open(Request(robots_url, headers={"User-Agent": USER_AGENT}), timeout=12) as response:
            raw_robots = response.read(200_001)
            if len(raw_robots) > 200_000:
                raise RuntimeError("robots.txt is too large")
            robots_text = raw_robots.decode("utf-8", errors="replace")
            if re.search(r"<\s*(?:!doctype|html)\b", robots_text[:500], re.IGNORECASE):
                raise RuntimeError("robots.txt returned HTML; crawling stopped")
            robots.parse(robots_text.splitlines())
    except HTTPError as error:
        if error.code == 429:
            raise RateLimited("Website returned HTTP 429 for robots.txt") from error
        if error.code != 404:
            raise RuntimeError("Could not read robots.txt; crawling stopped") from error
        robots.parse([])
    except (OSError, ValueError) as error:
        raise RuntimeError("Could not read robots.txt; crawling stopped") from error
    redirects.robots = robots
    if not robots.can_fetch(USER_AGENT, homepage):
        raise RobotsDisallowed("robots.txt disallows homepage")
    delay = max(robots.crawl_delay(USER_AGENT) or 0, 1)
    if delay > 10:
        raise RuntimeError("robots.txt crawl delay exceeds the pilot crawler limit")
    pending = [(-1, homepage)]
    scheduled = {homepage}
    visited: set[str] = set()
    type_counts: dict[str, int] = {}
    pages: list[WebPage] = []
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
        if urlparse(current).hostname != host or not robots.can_fetch(USER_AGENT, current):
            continue
        request = Request(current, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        try:
            if pages and delay:
                time.sleep(delay)
            with opener.open(request, timeout=12) as response:
                final_url = _public_http_url(response.url)
                if urlparse(final_url).hostname != host:
                    continue
                if "text/html" not in response.headers.get("Content-Type", ""):
                    continue
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    continue
                charset = response.headers.get_content_charset() or "utf-8"
        except HTTPError as error:
            if error.code == 429:
                raise RateLimited("Website returned HTTP 429") from error
            continue
        except (OSError, UnicodeError, ValueError, InvalidURL):
            continue
        if on_page:
            on_page(final_url, raw)
        try:
            decoded = raw.decode(charset, errors="replace")
        except LookupError:
            decoded = raw.decode("utf-8", errors="replace")
        page, links = extract_html(final_url, decoded)
        if page.text:
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
            if parsed.hostname != host or parsed.scheme not in {"http", "https"}:
                continue
            if target in scheduled:
                continue
            if any(hint in (parsed.path + " " + label).lower() for hint in PAGE_HINTS):
                candidates.append((_link_priority(parsed.path + " " + label), target))
                scheduled.add(target)
        pending.extend(candidates)
    return pages
