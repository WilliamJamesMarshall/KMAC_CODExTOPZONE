import io
import unittest
from email.message import Message
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import BaseHandler, build_opener
from urllib.response import addinfourl

from oss.crawler import CrawlError, RobotsDisallowed, crawl_site, decode_html, extract_html, has_readable_content


HTML = "<html><body><h1>Company</h1><p>Public products and services.</p>{}</body></html>"


class Transport(BaseHandler):
    handler_order = 100

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def http_open(self, request):
        self.requests.append(request.full_url)
        response = self.routes[request.full_url]
        if isinstance(response, Exception):
            raise response
        status, values, body = response
        headers = Message()
        for key, value in values.items():
            headers[key] = value
        result = addinfourl(io.BytesIO(body.encode()), headers, request.full_url, status)
        result.msg = "test response"
        return result

    https_open = http_open


def robots(text="User-agent: *\nAllow: /", status=200):
    return status, {"Content-Type": "text/plain"}, text


def page(links=""):
    return 200, {"Content-Type": "text/html; charset=utf-8"}, HTML.format(links)


def redirect(url, status=301):
    return status, {"Location": url}, ""


class CrawlerRedirectTests(unittest.TestCase):
    def test_legacy_meta_charset_preserves_company_name_and_business_functions(self):
        html = '<meta http-equiv="Content-Type" content="text/html; charset=euc-kr"><body>' \
               '<h1>(주)바이오빛</h1><div>항균 단백질 제품을 개발하고 공급합니다.</div></body>'
        page, _ = extract_html('https://example.com/', decode_html(html.encode('euc-kr'), None))
        self.assertIn('항균 단백질 제품을 개발', page.text)
        self.assertNotIn('\ufffd', page.text)

    def test_http_charset_has_precedence_and_unknown_charset_is_safe(self):
        html = '<meta charset="euc-kr"><body><p>제품을 개발하고 공급합니다.</p></body>'
        raw = html.encode('utf-8')
        self.assertEqual(decode_html(raw, 'utf-8'), html)
        self.assertIn('제품을 개발', decode_html(raw, 'unknown-encoding'))

    def test_heading_does_not_discard_adjacent_div_business_copy(self):
        page, _ = extract_html("https://example.com/", '<body><h1>회사소개</h1>'
            '<div>산업용 센서를 제조하고 품질검사 서비스를 제공합니다.</div></body>')
        self.assertIn("회사소개", page.text)
        self.assertIn("산업용 센서를 제조", page.text)

    def test_loading_and_title_are_not_collected_business_content(self):
        from oss.models import WebPage
        for text in ["TO TOP", "Loading...\nTO TOP", "회사소개"]:
            self.assertFalse(has_readable_content(WebPage("https://example.com", "회사소개", text)))

    def test_dns_error_is_reported_before_fetch_as_dns_failure(self):
        import socket
        with self.assertRaises(CrawlError) as caught:
            self.crawl("https://example.com/", {}, dns=lambda *args: (_ for _ in ()).throw(
                socket.gaierror(11001, "getaddrinfo failed")))
        self.assertEqual(caught.exception.code, "dns_failed")

    def test_linked_external_article_does_not_discard_homepage(self):
        pages = self.crawl("https://example.com/", {
            "https://example.com/robots.txt": robots(),
            "https://example.com/": page('<a href="/company/news">Company news</a>'),
            "https://example.com/company/news": redirect("https://news.example/article"),
        }, max_pages=2)
        self.assertEqual(len(pages), 1)
        self.assertNotIn("https://news.example/article", self.transport.requests)

    def test_meta_refresh_is_collected_as_same_host_navigation_without_browser(self):
        with patch("oss.browser_render.BrowserRenderer") as factory:
            pages = self.crawl("https://example.com/", {
                "https://example.com/robots.txt": robots(),
                "https://example.com/": (200, {"Content-Type": "text/html"},
                    "<meta http-equiv='Refresh' content='0; URL=default/'>"),
                "https://example.com/default/": page(),
            })
        self.assertEqual(pages[0].url, "https://example.com/default/")
        factory.assert_not_called()

    def crawl(self, url, routes, *, max_pages=1, dns=None):
        self.transport = Transport(routes)
        self.diagnostics = {}
        dns = dns or (lambda *args: [(2, 1, 6, "", ("93.184.216.34", 0))])
        with patch("oss.crawler.build_opener", side_effect=lambda *handlers: build_opener(*handlers, self.transport)), \
             patch("oss.browser_render.build_opener", side_effect=lambda *handlers: build_opener(*handlers, self.transport)), \
             patch("oss.crawler.socket.getaddrinfo", side_effect=dns), \
             patch("oss.crawler.time.sleep") as sleep:
            self.sleep = sleep
            return crawl_site(url, max_pages=max_pages, diagnostics=self.diagnostics)

    def test_www_redirects_for_robots_and_homepage_keep_canonical_internal_links(self):
        bare, canonical = "https://example.com", "https://www.example.com"
        routes = {
            bare + "/robots.txt": redirect(canonical + "/robots.txt", 307),
            canonical + "/robots.txt": robots(),
            bare + "/": redirect(canonical + "/", 307),
            canonical + "/": page(f'<a href="{bare}/product">Product</a>'),
            bare + "/product": redirect(canonical + "/product"),
            canonical + "/product": page(),
        }
        pages = self.crawl(bare + "/", routes, max_pages=2)
        self.assertEqual([p.url for p in pages], [canonical + "/", canonical + "/product"])
        self.assertEqual(self.diagnostics["canonical_url"], canonical + "/")
        self.assertEqual(self.diagnostics["redirects"][0]["http_status"], 307)
        self.assertEqual(self.diagnostics["redirects"][0]["request_kind"], "robots")

    def test_reverse_www_and_http_to_https_redirects(self):
        for initial, final in [("https://www.example.com", "https://example.com"),
                               ("http://example.com", "https://www.example.com")]:
            with self.subTest(initial=initial):
                routes = {initial + "/robots.txt": redirect(final + "/robots.txt"),
                          final + "/robots.txt": robots(), initial + "/": redirect(final + "/"),
                          final + "/": page()}
                self.assertEqual(self.crawl(initial + "/", routes)[0].url, final + "/")

    def test_destination_crawl_delay_also_applies_to_links_using_original_alias(self):
        initial, final = "https://example.com", "https://www.example.com"
        self.crawl(initial + "/", {
            initial + "/robots.txt": robots(),
            final + "/robots.txt": robots("User-agent: *\nCrawl-delay: 4"),
            initial + "/": redirect(final + "/"),
            final + "/": page(f'<a href="{initial}/product">Product</a>'),
            initial + "/product": redirect(final + "/product"),
            final + "/product": page(),
        }, max_pages=2)
        self.sleep.assert_called_once_with(4)

    def test_destination_robots_is_checked_before_redirected_body(self):
        routes = {"https://example.com/robots.txt": robots(),
                  "https://example.com/": redirect("https://www.example.com/"),
                  "https://www.example.com/robots.txt": robots("User-agent: *\nDisallow: /")}
        with self.assertRaises(RobotsDisallowed):
            self.crawl("https://example.com/", routes)
        self.assertNotIn("https://www.example.com/", self.transport.requests)
        self.assertEqual(self.diagnostics["request_kind"], "page")

    def test_redirected_robots_disallow_stops_before_homepage(self):
        routes = {"https://example.com/robots.txt": redirect("https://www.example.com/robots.txt"),
                  "https://www.example.com/robots.txt": robots("User-agent: *\nDisallow: /")}
        with self.assertRaises(RobotsDisallowed):
            self.crawl("https://example.com/", routes)
        self.assertNotIn("https://example.com/", self.transport.requests)

    def test_cross_domain_subdomain_private_address_and_port_redirects_are_blocked(self):
        for target in ["https://other.com/", "https://shop.example.com/", "https://127.0.0.1/",
                       "https://www.example.com:8443/", "https://user:password@www.example.com/"]:
            for kind in ["robots", "page"]:
                with self.subTest(target=target, kind=kind):
                    routes = {"https://example.com/robots.txt": robots(), "https://example.com/": redirect(target)}
                    if kind == "robots":
                        routes["https://example.com/robots.txt"] = redirect(target)
                    with self.assertRaises(CrawlError) as caught:
                        self.crawl("https://example.com/", routes)
                    self.assertEqual(caught.exception.code, "redirect_blocked")
                    self.assertNotIn(target, self.transport.requests)
                    self.assertNotIn("password", str(self.diagnostics))

    def test_www_alias_resolving_to_private_ip_is_blocked(self):
        def dns(host, *args):
            address = "127.0.0.1" if host.startswith("www.") else "93.184.216.34"
            return [(2, 1, 6, "", (address, 0))]
        routes = {"https://example.com/robots.txt": redirect("https://www.example.com/robots.txt")}
        with self.assertRaises(CrawlError) as caught:
            self.crawl("https://example.com/", routes, dns=dns)
        self.assertEqual(caught.exception.code, "redirect_blocked")

    def test_redirect_loop_is_bounded(self):
        for path in ["/robots.txt", "/"]:
            with self.subTest(path=path):
                routes = {"https://example.com/robots.txt": robots(),
                          "https://www.example.com/robots.txt": robots(),
                          "https://example.com" + path: redirect("https://www.example.com" + path),
                          "https://www.example.com" + path: redirect("https://example.com" + path)}
                with self.assertRaises(CrawlError) as caught:
                    self.crawl("https://example.com/", routes)
                self.assertEqual(caught.exception.code, "redirect_loop")
                self.assertLess(len(self.transport.requests), 20)

    def test_robots_absent_allows_pages_and_invalid_policies_stop(self):
        self.assertEqual(len(self.crawl("https://example.com/", {
            "https://example.com/robots.txt": robots("", 404), "https://example.com/": page(),
        })), 1)
        for policy, code in [(robots("", 429), "rate_limited"), (robots("", 403), "robots_unavailable"),
                             (robots("<html>Not a policy</html>"), "robots_unavailable"),
                             (robots("User-agent: *\nCrawl-delay: 11"), "crawl_delay_exceeded"),
                             (TimeoutError(), "fetch_timeout"), (URLError(TimeoutError()), "fetch_timeout")]:
            with self.subTest(code=code):
                with self.assertRaises(CrawlError) as caught:
                    self.crawl("https://example.com/", {"https://example.com/robots.txt": policy})
                self.assertEqual(caught.exception.code, code)

    def test_page_errors_have_specific_codes(self):
        for response, code in [(robots("", 429), "rate_limited"), (robots("", 503), "fetch_failed"),
                               (TimeoutError(), "fetch_timeout"), (URLError(TimeoutError()), "fetch_timeout"),
                               ((200, {"Content-Type": "text/html"}, ""), "no_content")]:
            with self.subTest(code=code):
                with self.assertRaises(CrawlError) as caught:
                    self.crawl("https://example.com/", {
                        "https://example.com/robots.txt": robots(), "https://example.com/": response,
                    })
                self.assertEqual(caught.exception.code, code)

    def test_diagnostics_exclude_query_values(self):
        self.crawl("https://example.com/?token=PRIVATE", {
            "https://example.com/robots.txt": robots(),
            "https://example.com/?token=PRIVATE": redirect("https://www.example.com/?token=PRIVATE"),
            "https://www.example.com/robots.txt": robots(),
            "https://www.example.com/?token=PRIVATE": page(),
        })
        self.assertNotIn("PRIVATE", str(self.diagnostics))

    def test_javascript_shell_is_rendered_and_internal_page_is_discovered(self):
        shell = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
        script = """setTimeout(() => {
            document.querySelector('#root').innerHTML = '<h1>Agricultural company</h1>' +
            '<p>We provide agricultural production and distribution services using our public business expertise.</p>' +
            '<a href="/company/about">Company information</a>';
            fetch('https://127.0.0.1/private').catch(() => {});
            fetch('https://other.example/api').catch(() => {});
            fetch('/write', {method:'POST', body:'do not send'}).catch(() => {});
        }, 100);"""
        pages = self.crawl("https://example.com/", {
            "https://example.com/robots.txt": robots(),
            "https://example.com/": (200, {"Content-Type": "text/html"}, shell),
            "https://example.com/app.js": (200, {"Content-Type": "application/javascript"}, script),
            "https://example.com/company/about": page(),
        }, max_pages=2)
        self.assertEqual(len(pages), 2)
        self.assertIn("agricultural production", pages[0].text)
        self.assertEqual(pages[1].url, "https://example.com/company/about")
        self.assertEqual(len(self.diagnostics["rendering"]), 1)
        for forbidden in ["https://127.0.0.1/private", "https://other.example/api", "https://example.com/write"]:
            self.assertNotIn(forbidden, self.transport.requests)

    def test_static_content_never_launches_browser_and_renderer_is_closed_on_error(self):
        from unittest.mock import MagicMock
        with patch("oss.browser_render.BrowserRenderer") as factory:
            self.crawl("https://example.com/", {
                "https://example.com/robots.txt": robots(), "https://example.com/": page(),
            })
            factory.assert_not_called()
            renderer = MagicMock()
            renderer.render.side_effect = CrawlError("Missing runtime", code="render_unavailable")
            factory.return_value.__enter__.return_value = renderer
            with self.assertRaises(CrawlError) as caught:
                self.crawl("https://example.com/", {
                    "https://example.com/robots.txt": robots(),
                    "https://example.com/": (200, {"Content-Type": "text/html"}, '<body><script src="/app.js"></script></body>'),
                })
            self.assertEqual(caught.exception.code, "render_unavailable")
            factory.return_value.__exit__.assert_called_once()

    def test_rendering_does_not_bypass_asset_robots_policy(self):
        with self.assertRaises(RobotsDisallowed):
            self.crawl("https://example.com/", {
                "https://example.com/robots.txt": robots("User-agent: *\nDisallow: /app.js"),
                "https://example.com/": (200, {"Content-Type": "text/html"},
                                         '<body><div id="root"></div><script src="/app.js"></script></body>'),
            })
        self.assertNotIn("https://example.com/app.js", self.transport.requests)

    def test_unreadable_dynamic_subpage_preserves_collected_homepage(self):
        with patch("oss.browser_render.BrowserRenderer") as factory:
            factory.return_value.__enter__.return_value.render.side_effect = CrawlError(
                "No dynamic content", code="render_failed",
            )
            pages = self.crawl("https://example.com/", {
                "https://example.com/robots.txt": robots(),
                "https://example.com/": page('<a href="/company/empty">Company</a>'),
                "https://example.com/company/empty": (200, {"Content-Type": "text/html"},
                                                      '<body><script src="/app.js"></script></body>'),
            }, max_pages=2)
            self.assertEqual(len(pages), 1)
            self.assertEqual(pages[0].url, "https://example.com/")


if __name__ == "__main__":
    unittest.main()
