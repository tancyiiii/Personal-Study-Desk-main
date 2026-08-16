"""Chinese-accessible web search tools with observable fallbacks."""

from __future__ import annotations

import json
from typing import Callable, List, Optional

import requests
from bs4 import BeautifulSoup
from phi.tools import Toolkit


TraceCallback = Optional[Callable[[str, str], None]]


class ChineseSearchTool(Toolkit):
    """Search Bing China, falling back to Baidu when Bing is unavailable."""

    def __init__(
        self,
        max_results: int = 8,
        trace_callback: TraceCallback = None,
    ):
        super().__init__(name="chinese_web_search")
        self.max_results = max_results
        self.trace_callback = trace_callback
        self.register(self.search_chinese)

    def _trace(self, stage: str, detail: str) -> None:
        if self.trace_callback:
            self.trace_callback(stage, detail)

    def search_chinese(self, query: str) -> str:
        """Search Chinese-language learning resources and return results."""
        self._trace("web_search", f"使用 Bing 中国区检索：{query}")
        results = self._search_bing(query)
        if not results:
            self._trace("web_search", "Bing 无结果，切换到 Baidu")
            results = self._search_baidu(query)
        payload = {
            "engine": "bing_cn" if results else "none",
            "results": results[: self.max_results],
        }
        self._trace("web_search", f"获得 {len(payload['results'])} 条结果")
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _request(url: str, params: dict) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        }
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text

    def _search_bing(self, query: str) -> List[dict]:
        try:
            html = self._request(
                "https://www.bing.com/search",
                {
                    "q": query,
                    "setlang": "zh-hans",
                    "mkt": "zh-CN",
                    "cc": "cn",
                    "count": str(self.max_results),
                },
            )
        except Exception as exc:
            self._trace("web_search", f"Bing 请求失败：{exc}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[dict] = []
        seen_urls = set()
        for item in soup.select("li.b_algo"):
            link = item.select_one("h2 a")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            url = link.get("href") or ""
            if not title or not url or url in seen_urls:
                continue
            snippet_node = item.select_one(".b_caption p") or item.select_one("p")
            snippet = (
                snippet_node.get_text(" ", strip=True)
                if snippet_node
                else ""
            )
            seen_urls.add(url)
            results.append(
                {"title": title, "url": url, "snippet": snippet}
            )
        return results

    def _search_baidu(self, query: str) -> List[dict]:
        try:
            html = self._request(
                "https://www.baidu.com/s", {"wd": query, "rn": "20"}
            )
        except Exception as exc:
            self._trace("web_search", f"Baidu 请求失败：{exc}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[dict] = []
        seen_urls = set()
        for item in soup.select("div.result, div.c-container"):
            link = item.select_one("h3 a")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            url = link.get("href") or ""
            if not title or not url or url in seen_urls:
                continue
            snippet_node = item.select_one(".c-abstract") or item.select_one("p")
            snippet = (
                snippet_node.get_text(" ", strip=True)
                if snippet_node
                else ""
            )
            seen_urls.add(url)
            results.append(
                {"title": title, "url": url, "snippet": snippet}
            )
        return results

