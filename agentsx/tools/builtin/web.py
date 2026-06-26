"""Web fetch and search tools."""

from __future__ import annotations

import html
import re
import urllib.parse

from agentsx.tools import tool


def _html_to_text(html_content: str) -> str:
    """Convert HTML to readable text without external dependencies."""
    text = html_content
    text = re.sub(
        r"<(?:br\s*/?|p|div|h[1-6]|li|tr)[^>]*>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'<a\s[^>]*href=["\']?([^"\'>\s]+)["\']?[^>]*>'
        r"(.*?)</a>",
        r"\2 (\1)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@tool(description="Fetch content from a URL and return it as text.")
def tool_web_fetch(url: str, format: str = "text") -> str:  # noqa: A002
    """Fetch a URL and return its content.

    Args:
        url: URL to fetch.
        format: Output format -- ``"text"`` (default) or ``"html"``.

    Returns:
        The page content in the requested format.
    """
    import httpx  # noqa: PLC0415

    try:
        response = httpx.get(
            url,
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; "
                    "AgentsX/0.1.0; +https://github.com/agentsx)"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Error fetching {url}: {exc}"

    if format == "html":
        return response.text[:100000]

    text = _html_to_text(response.text)
    return text[:100000]


@tool(description="Search the web for information.")
def tool_web_search(query: str, num_results: int = 5) -> str:
    """Search the web and return formatted results.

    Args:
        query: Search query string.
        num_results: Number of results to return (default 5, max 10).

    Returns:
        Search results with title and URL.
    """
    import httpx  # noqa: PLC0415

    num_results = min(num_results, 10)
    encoded = urllib.parse.quote(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"

    try:
        response = httpx.get(
            url,
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Error searching for '{query}': {exc}"

    body = response.text

    title_pattern = re.compile(
        r'<a[^>]+class="result__title"[^>]*>'
        r'.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>'
        r"(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )

    titles = title_pattern.findall(body)
    snippets = snippet_pattern.findall(body)

    if not titles:
        link_pattern = re.compile(
            r'<a[^>]+href="([^"]+)"[^>]*>([^<]{10,})</a>',
            re.IGNORECASE,
        )
        links = link_pattern.findall(body)
        if not links:
            return f"No results found for '{query}'"
        seen: set[str] = set()
        results: list[str] = []
        for href, text_content in links[:num_results]:
            if href in seen:
                continue
            seen.add(href)
            clean_text = html.unescape(text_content.strip())
            results.append(f"- {clean_text}\n  {href}")
        return "\n\n".join(results)

    count = min(len(titles), num_results)
    results = []
    for i in range(count):
        href, title_text = titles[i]
        clean_title = html.unescape(title_text.strip())
        snippet = html.unescape(snippets[i].strip()) if i < len(snippets) else ""
        result = f"- {clean_title}\n  {href}"
        if snippet:
            result += f"\n  {snippet[:200]}"
        results.append(result)

    return "\n\n".join(results)
