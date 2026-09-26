"""
Autonomous Web Scraper Sub-Agent powered by NVIDIA NIM.
"""

from vision.cognitive.agents.base_agent import BaseAgent
from vision.config import config


class ScraperAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="ScraperAgent",
            dedicated_api_key=config.SCRAPER_AGENT_LLM_API,
            allowed_tools=[
                "fetch_webpage_content",
                "browser_get_page_content",
                "search_web",
                "search_google_web",
                "open_website",
                "download_file_from_url",
            ],
        )

    def get_system_prompt(self) -> str:
        return """You are the VISION Web Scraper & Information Extraction Agent.
You analyze raw HTML, extract key data points, summarize articles, and format research findings into structured markdown or JSON.
"""
