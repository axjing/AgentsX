"""Tests for web tools: HTML parsing, web fetch, and web search."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from agentsx.tools.builtin.web.web import (
    _html_to_text,
    tool_web_fetch,
    tool_web_search,
)


class TestHtmlToText:
    """Tests for _html_to_text utility function."""

    def test_strip_basic_tags(self) -> None:
        raw = "<p>Hello <b>World</b></p>"
        assert _html_to_text(raw) == "Hello World"

    def test_newlines_for_block_elements(self) -> None:
        raw = "<div>Line 1</div><p>Line 2</p><br/>Line 3"
        result = _html_to_text(raw)
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_anchor_tag_conversion(self) -> None:
        raw = 'Visit <a href="https://example.com">Example</a> today!'
        result = _html_to_text(raw)
        assert "Example (https://example.com)" in result

    def test_html_entities_replacement(self) -> None:
        raw = "&lt;tag&gt; &amp; &quot;quote&quot; &#39;single&#39; &nbsp;"
        result = _html_to_text(raw)
        assert "<tag> & \"quote\" 'single'" in result

    def test_excessive_whitespace_collapse(self) -> None:
        raw = "<p>Word1       Word2</p>\n\n\n\n<p>Word3</p>"
        result = _html_to_text(raw)
        assert "Word1 Word2\n\nWord3" == result


class TestToolWebFetch:
    """Tests for tool_web_fetch."""

    def test_fetch_text_success(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.text = "<html><body><h1>Title</h1><p>Body text</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result = tool_web_fetch.fn(url="https://example.com", format="text")
            mock_get.assert_called_once()
            assert "Title" in result
            assert "Body text" in result

    def test_fetch_html_success(self) -> None:
        raw_html = "<html><body><h1>Direct HTML</h1></body></html>"
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.text = raw_html
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            result = tool_web_fetch.fn(url="https://example.com", format="html")
            assert result == raw_html

    def test_fetch_http_error(self) -> None:
        with patch(
            "httpx.get",
            side_effect=httpx.ConnectError("Failed to connect"),
        ):
            result = tool_web_fetch.fn(url="https://invalid.domain")
            assert "Error fetching https://invalid.domain:" in result
            assert "Failed to connect" in result

    @pytest.mark.asyncio
    async def test_tool_call_interface(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.text = "<p>Async Call Content</p>"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            res = await tool_web_fetch.call(url="https://example.com")
            assert "Async Call Content" in res.content


class TestToolWebSearch:
    """Tests for tool_web_search."""

    def test_search_with_standard_snippets(self) -> None:
        html_page = """
        <div class="results">
            <a class="result__title">
                <a href="https://example.com/item1">Example Item 1</a>
            </a>
            <a class="result__snippet">This is snippet 1</a>
            <a class="result__title">
                <a href="https://example.com/item2">Example Item 2</a>
            </a>
            <a class="result__snippet">This is snippet 2</a>
        </div>
        """
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.text = html_page
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result = tool_web_search.fn(query="python test", num_results=2)
            mock_get.assert_called_once()
            assert "Example Item 1" in result
            assert "https://example.com/item1" in result
            assert "This is snippet 1" in result
            assert "Example Item 2" in result

    def test_search_fallback_links(self) -> None:
        html_page = """
        <div>
            <a href="https://example.com/link1">Long anchor text 1</a>
            <a href="https://example.com/link2">Long anchor text 2</a>
        </div>
        """
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.text = html_page
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            result = tool_web_search.fn(query="fallback search", num_results=2)
            assert "Long anchor text 1" in result
            assert "https://example.com/link1" in result

    def test_search_no_results(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.text = "<div>Nothing here</div>"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            result = tool_web_search.fn(query="nonexistent term")
            assert "No results found for 'nonexistent term'" in result

    def test_search_http_error(self) -> None:
        with patch("httpx.get", side_effect=httpx.TimeoutException("Timeout")):
            result = tool_web_search.fn(query="timeout search")
            assert "Error searching for 'timeout search': Timeout" in result
