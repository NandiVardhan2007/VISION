"""
Live Web Search, Real-Time Intelligence, and Web Browsing Tools for VISION.
Supports real-time DuckDuckGo web search, webpage text extraction, and live weather telemetry.
"""

import re
import warnings
from typing import Optional, List, Dict, Any
from vision.tools.registry import tool
from vision.logger import logger

warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*duckduckgo_search.*")

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

try:
    import httpx
except ImportError:
    httpx = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


@tool(name="search_web", description="Search the live internet in real-time for latest news, facts, documentation, events, weather, technology, sports, and answers.")
def search_web(query: str) -> str:
    """Perform real-time web search via DuckDuckGo."""
    if not DDGS:
        return "Error: DDGS search package is not available."

    try:
        logger.info(f"[WebTool] Searching internet for: '{query}'")
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=5))

        if not results:
            return f"No search results found for '{query}'."

        formatted_lines = [f"Live Web Search Results for '{query}':\n"]
        for idx, r in enumerate(results, 1):
            title = r.get("title", "No Title")
            snippet = r.get("body") or r.get("description") or ""
            link = r.get("href") or r.get("url") or ""
            formatted_lines.append(f"[{idx}] {title}\nSummary: {snippet}\nSource: {link}\n")

        return "\n".join(formatted_lines)
    except Exception as e:
        logger.error(f"[WebTool] Search error: {e}")
        return f"Error performing web search: {e}"


@tool(name="fetch_webpage_content", description="Fetch and extract the readable text content of a specific web URL or article.")
def fetch_webpage_content(url: str) -> str:
    """Download and clean the readable body content from a webpage."""
    if not httpx:
        return "Error: httpx package is not installed."

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text

        if BeautifulSoup:
            soup = BeautifulSoup(html, "html.parser")
            # Remove scripts, styles, navigations
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n")
        else:
            text = re.sub(r"<[^>]+>", "", html)

        # Collapse whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)[:3500]

        return f"Extracted Content from {url}:\n\n{clean_text}"
    except Exception as e:
        return f"Error fetching webpage content from '{url}': {e}"


@tool(name="get_weather_forecast", description="Get the live current weather, temperature, humidity, and condition for any city or location.")
def get_weather_forecast(location: str = "Hyderabad") -> str:
    """Retrieve live weather report for the specified city."""
    if not httpx:
        return "Error: httpx is not installed."

    clean_loc = location.strip().replace(" ", "+")
    url = f"https://wttr.in/{clean_loc}?format=j1"

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return f"Unable to fetch weather data for '{location}'."
            data = resp.json()

        curr = data["current_condition"][0]
        temp_c = curr.get("temp_C", "N/A")
        feels_like_c = curr.get("FeelsLikeC", "N/A")
        desc = curr.get("weatherDesc", [{}])[0].get("value", "N/A")
        humidity = curr.get("humidity", "N/A")
        wind_kmph = curr.get("windspeedKmph", "N/A")

        # Today's forecast min/max
        weather_today = data.get("weather", [{}])[0]
        max_temp = weather_today.get("maxtempC", "N/A")
        min_temp = weather_today.get("mintempC", "N/A")

        return (
            f"Weather Report for {location.title()}:\n"
            f"- Condition: {desc}\n"
            f"- Temperature: {temp_c}°C (Feels like {feels_like_c}°C)\n"
            f"- High / Low Today: {max_temp}°C / {min_temp}°C\n"
            f"- Humidity: {humidity}%\n"
            f"- Wind Speed: {wind_kmph} km/h"
        )
    except Exception as e:
        return f"Error retrieving weather report: {e}"
