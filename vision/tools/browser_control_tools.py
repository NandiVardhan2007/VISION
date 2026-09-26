"""
Antigravity-Grade Autonomous Web Browser Agent & Control System for VISION AI OS.
Provides full interactive control (clicking by index/selector, form filling, typing,
hovering, dropdown selection, multi-tab handling, DOM accessibility tree scanning,
visual screenshot capture, and autonomous goal-driven subagent execution) with a visible browser window.
"""

import os
import json
import asyncio
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from vision.tools.registry import tool
from vision.logger import logger

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"

try:
    from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page, Dialog
except Exception:
    # playwright imports native/driver components at import time; a broken or
    # partial install can raise beyond ImportError. Catch broadly so importing
    # this module (and the whole browser-tool chain) degrades gracefully.
    async_playwright = None
    Playwright = None
    Browser = None
    BrowserContext = None
    Page = None
    Dialog = None


class BrowserController:
    """Singleton controller managing the live Playwright browser session with Antigravity-grade features."""
    _instance: Optional["BrowserController"] = None

    def __init__(self):
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._pages: List[Page] = []
        self._element_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._screenshots_dir = DATA_DIR / "screenshots"
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls) -> "BrowserController":
        if cls._instance is None:
            cls._instance = BrowserController()
        return cls._instance

    async def _on_dialog(self, dialog: Dialog):
        """Auto-accept JavaScript alert/confirm/prompt dialogs to prevent browser hangs."""
        try:
            logger.info(f"[BrowserController] Auto-accepting dialog: '{dialog.message}' (type={dialog.type})")
            await dialog.accept()
        except Exception as e:
            logger.warning(f"[BrowserController] Dialog handling note: {e}")

    def _on_new_page(self, page: Page):
        """Track newly opened tabs/popups."""
        logger.info(f"[BrowserController] New browser tab detected.")
        if page not in self._pages:
            self._pages.append(page)
        # Popups get their own dialog handler too, otherwise an alert()/confirm()
        # raised on a popup tab has no listener and blocks the whole browser.
        try:
            page.on("dialog", lambda d: asyncio.create_task(self._on_dialog(d)))
        except Exception as e:
            logger.debug(f"[BrowserController] Could not attach dialog handler to popup: {e}")
        self._page = page

    async def ensure_page(self, headless: bool = False) -> Page:
        """Ensure an active Playwright browser page is running and return it with stealth settings."""
        if async_playwright is None:
            raise RuntimeError("Playwright is not installed. Please run 'pip install playwright' and 'playwright install chromium'.")

        async with self._lock:
            # Check if active page is still alive
            if self._page is not None and not self._page.is_closed() and self._browser is not None and self._browser.is_connected():
                return self._page

            logger.info(f"[BrowserController] Launching visible Chromium browser (headless={headless})...")
            if self._pw is None:
                self._pw = await async_playwright().start()

            # If context/page setup fails after launch(), the Chromium process
            # would leak: self._browser stays set but self._page is None, so the
            # next ensure_page() launches ANOTHER browser and orphans this one.
            # Tear down whatever was created before re-raising.
            try:
                self._browser = await self._pw.chromium.launch(
                    headless=headless,
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--no-default-browser-check",
                        "--disable-infobars",
                        "--no-sandbox"
                    ]
                )

                self._context = await self._browser.new_context(
                    viewport=None,  # Match window size
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    locale="en-US",
                    timezone_id="Asia/Kolkata",
                    permissions=["geolocation", "notifications"]
                )

                # Apply stealth scripts to evade bot detection
                await self._context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                """)

                # Attach multi-tab tracker
                self._context.on("page", self._on_new_page)

                self._page = await self._context.new_page()
                self._page.on("dialog", lambda d: asyncio.create_task(self._on_dialog(d)))
                self._page.set_default_timeout(15000)
                self._pages = [self._page]
                return self._page
            except Exception:
                if self._browser is not None:
                    try:
                        await self._browser.close()
                    except Exception:
                        pass
                self._browser = None
                self._context = None
                self._page = None
                self._pages = []
                raise

    async def get_current_page(self) -> Optional[Page]:
        if self._page is not None and not self._page.is_closed():
            return self._page
        # Fallback to any remaining active tab
        for p in self._pages:
            if not p.is_closed():
                self._page = p
                return self._page
        return None

    def store_element_cache(self, elements: List[Dict[str, Any]]):
        """Store numbered element cache for index-based targeting."""
        self._element_cache.clear()
        for el in elements:
            idx = str(el.get("index", ""))
            if idx:
                self._element_cache[idx] = el

    # Bare words that are genuine HTML tag selectors (as opposed to human-readable
    # button/link text like "Login" or "Next"). Used to disambiguate resolve_target.
    _HTML_TAGS = {
        "a", "button", "input", "textarea", "select", "option", "div", "span",
        "form", "img", "label", "ul", "ol", "li", "table", "tr", "td", "th",
        "nav", "header", "footer", "section", "article", "main", "aside", "iframe",
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "body", "html", "svg", "path",
    }

    @staticmethod
    def _escape_selector_text(text: str) -> str:
        """Escape backslashes and double quotes so text can sit inside a :text("...") selector."""
        return str(text).replace("\\", "\\\\").replace('"', '\\"')

    @classmethod
    def _looks_like_selector(cls, s: str) -> bool:
        """Heuristically decide whether a target string is a CSS/Playwright/XPath selector
        (vs. plain human-readable element text such as a button label)."""
        if not s:
            return True
        if s.startswith(("#", ".", "[", "//", "*", ":", "(")):
            return True
        if any(tok in s for tok in (">>", "text=", "xpath=", "css=")):
            return True
        if any(ch in s for ch in "#.[]>=~*+"):
            return True
        # Multi-word strings are human text, never a CSS type selector.
        if " " in s.strip():
            return False
        # A single bare word is only a selector when it names a real HTML tag.
        return s.strip().lower() in cls._HTML_TAGS

    def resolve_target(self, target: str) -> str:
        """Resolve numeric element index (e.g. '1', '2') or raw selector into valid selector."""
        target_str = str(target).strip()
        if target_str in self._element_cache:
            resolved = self._element_cache[target_str].get("selector")
            if resolved:
                logger.debug(f"[BrowserController] Resolved index [{target_str}] -> '{resolved}'")
                return resolved
        # Plain button/link text (advertised as supported) -> build a safe, quote-escaped
        # text selector so labels like 'Sign In' or 'Add to cart' actually match.
        if not self._looks_like_selector(target_str):
            escaped = self._escape_selector_text(target_str)
            resolved = f':text("{escaped}")'
            logger.debug(f"[BrowserController] Treating '{target_str}' as text -> {resolved}")
            return resolved
        return target_str

    async def close(self) -> str:
        """Close active browser session and release resources."""
        async with self._lock:
            try:
                if self._context:
                    await self._context.close()
                if self._browser:
                    await self._browser.close()
                if self._pw:
                    await self._pw.stop()
            except Exception as e:
                logger.warning(f"[BrowserController] Cleanup note: {e}")
            finally:
                self._page = None
                self._pages.clear()
                self._context = None
                self._browser = None
                self._pw = None
                self._element_cache.clear()
            logger.info("[BrowserController] Browser session closed.")
            return "Browser closed successfully."


controller = BrowserController.get_instance()


@tool(name="browser_open", description="Launch a visible Chromium web browser window and open the specified URL (e.g. Google, YouTube, GitHub, portals).")
async def browser_open(url: str = "https://www.google.com") -> str:
    """Launch visible browser window and navigate to a URL."""
    try:
        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("about:"):
            url = "https://" + url

        page = await controller.ensure_page(headless=False)
        logger.info(f"[BrowserControl] Navigating to '{url}'...")
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        title = await page.title()
        return f"Browser opened successfully to '{url}'. Page Title: '{title}'."
    except Exception as e:
        logger.error(f"[BrowserControl] browser_open failed: {e}")
        return f"Error opening browser at '{url}': {e}"


@tool(name="browser_navigate", description="Navigate the current active browser page to a new web URL.")
async def browser_navigate(url: str) -> str:
    """Navigate current browser tab to URL."""
    try:
        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("about:"):
            url = "https://" + url

        page = await controller.ensure_page(headless=False)
        logger.info(f"[BrowserControl] Navigating active tab to '{url}'...")
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        title = await page.title()
        return f"Navigated to '{url}'. Page Title: '{title}'."
    except Exception as e:
        logger.error(f"[BrowserControl] browser_navigate failed: {e}")
        return f"Error navigating to '{url}': {e}"


@tool(name="browser_click", description="Click on an element using its index number (e.g. '1', '2' from interactive elements list), CSS selector, or button text.")
async def browser_click(target: str) -> str:
    """Click on a webpage element matching the index, selector, or text."""
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open. Use 'browser_open' first."

        selector = controller.resolve_target(target)
        logger.info(f"[BrowserControl] Clicking element: target='{target}', resolved='{selector}'")
        
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=8000)
        await loc.click()
        await page.wait_for_timeout(1000)
        title = await page.title()
        return f"Successfully clicked on '{target}' (`{selector}`). Current Page Title: '{title}', URL: {page.url}"
    except Exception as e:
        logger.error(f"[BrowserControl] browser_click failed: {e}")
        return f"Error clicking element '{target}': {e}. Try inspecting interactive elements using 'browser_get_interactive_elements'."


@tool(name="browser_type", description="Type text into an input field, search box, or textarea using its index number (e.g. '1', '2') or CSS selector.")
async def browser_type(target: str, text: str, press_enter: bool = False, clear_first: bool = True) -> str:
    """Fill or type text into a designated element."""
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open. Use 'browser_open' first."

        selector = controller.resolve_target(target)
        logger.info(f"[BrowserControl] Typing into target='{target}' ('{selector}'): '{text}' (press_enter={press_enter})")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=8000)
        
        if clear_first:
            await loc.fill("")
            await loc.fill(text)
        else:
            await loc.type(text, delay=40)

        if press_enter:
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1500)

        return f"Successfully typed '{text}' into '{target}' (`{selector}`)." + (" (Pressed Enter)" if press_enter else "")
    except Exception as e:
        logger.error(f"[BrowserControl] browser_type failed: {e}")
        return f"Error typing into '{target}': {e}"


@tool(name="browser_hover", description="Hover mouse over an element by index number or selector to trigger dropdown menus or tooltips.")
async def browser_hover(target: str) -> str:
    """Hover over an element."""
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open."

        selector = controller.resolve_target(target)
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=8000)
        await loc.hover()
        await page.wait_for_timeout(500)
        return f"Hovered over '{target}' (`{selector}`)."
    except Exception as e:
        return f"Error hovering over '{target}': {e}"


@tool(name="browser_select_option", description="Select an option from a <select> dropdown by index number/selector and the option value or label text.")
async def browser_select_option(target: str, value_or_label: str) -> str:
    """Select dropdown option."""
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open."

        selector = controller.resolve_target(target)
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=8000)
        await loc.select_option(label=value_or_label)
        return f"Selected option '{value_or_label}' in '{target}'."
    except Exception as e:
        # Fallback to value
        try:
            loc = page.locator(controller.resolve_target(target)).first
            await loc.select_option(value=value_or_label)
            return f"Selected option value '{value_or_label}' in '{target}'."
        except Exception as e2:
            return f"Error selecting option '{value_or_label}' in '{target}': {e2}"


@tool(name="browser_press_key", description="Press a keyboard key (e.g. Enter, Tab, Escape, ArrowDown, ArrowUp, Space, Backspace) on the active page.")
async def browser_press_key(key: str) -> str:
    """Send keypress to active browser window."""
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open."

        logger.info(f"[BrowserControl] Pressing key '{key}'")
        await page.keyboard.press(key)
        await page.wait_for_timeout(500)
        return f"Pressed key '{key}' in browser."
    except Exception as e:
        return f"Error pressing key '{key}': {e}"


@tool(name="browser_scroll", description="Scroll the active browser page 'up' or 'down' by a specified pixel amount, or 'top' / 'bottom'.")
async def browser_scroll(direction: str = "down", amount: int = 500) -> str:
    """Scroll webpage up/down or to bounds."""
    # amount is interpolated straight into page.evaluate() JS; coerce to a real
    # int so a stringified/garbage value can't inject arbitrary script or crash.
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 500
    amount = max(0, min(amount, 100000))
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open."

        dir_clean = direction.strip().lower()
        if dir_clean == "bottom":
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            return "Scrolled to the bottom of the page."
        elif dir_clean == "top":
            await page.evaluate("window.scrollTo(0, 0)")
            return "Scrolled to the top of the page."
        elif dir_clean == "up":
            await page.evaluate(f"window.scrollBy(0, -{amount})")
            return f"Scrolled up by {amount}px."
        else:
            await page.evaluate(f"window.scrollBy(0, {amount})")
            return f"Scrolled down by {amount}px."
    except Exception as e:
        return f"Error scrolling page: {e}"


@tool(name="browser_get_page_content", description="Extract and read the visible text content from the current active web page.")
async def browser_get_page_content(max_chars: int = 4000) -> str:
    """Get clean body text from active webpage."""
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open."

        title = await page.title()
        url = page.url
        # Extract readable inner text
        text = await page.evaluate("""() => {
            const clone = document.body.cloneNode(true);
            const removeTags = ['script', 'style', 'noscript', 'svg'];
            removeTags.forEach(tag => {
                const elements = clone.querySelectorAll(tag);
                elements.forEach(el => el.remove());
            });
            return clone.innerText || "";
        }""")

        cleaned = "\n".join([line.strip() for line in text.splitlines() if line.strip()])
        truncated = cleaned[:max_chars]
        if len(cleaned) > max_chars:
            truncated += f"\n... [Truncated: showing first {max_chars} characters of {len(cleaned)} total]"

        return f"Current Page: {title}\nURL: {url}\n\nContent:\n{truncated}"
    except Exception as e:
        return f"Error extracting page text: {e}"


@tool(name="browser_get_interactive_elements", description="Scan the active page and list clickable buttons, inputs, links, and forms with assigned [index] numbers for instant targeting.")
async def browser_get_interactive_elements() -> str:
    """Inspect and return interactive elements from the current page with index numbers."""
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open."

        elements_data = await page.evaluate("""() => {
            const results = [];
            const interactive = document.querySelectorAll('button, a, input, textarea, select, [role="button"], [role="link"], [role="textbox"], [role="combobox"]');
            let idx = 1;
            for (const el of interactive) {
                if (idx > 40) break; // limit to top 40 interactive elements
                const rect = el.getBoundingClientRect();
                const isVisible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
                if (!isVisible) continue;

                const tag = el.tagName.toLowerCase();
                const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                const type = el.getAttribute('type') || '';
                const id = el.id ? `#${el.id}` : '';
                const name = el.getAttribute('name') ? `[name="${el.getAttribute('name')}"]` : '';
                
                let selector = '';
                if (el.id) {
                    selector = `#${el.id}`;
                } else if (tag === 'button' && text) {
                    selector = `button:has-text("${text.slice(0, 25)}")`;
                } else if (tag === 'a' && text) {
                    selector = `a:has-text("${text.slice(0, 25)}")`;
                } else if (name) {
                    selector = `${tag}${name}`;
                } else if (el.placeholder) {
                    selector = `${tag}[placeholder="${el.placeholder}"]`;
                } else {
                    selector = tag;
                }

                results.push({
                    index: idx++,
                    tag: tag,
                    type: type,
                    text: text.slice(0, 40),
                    selector: selector
                });
            }
            return results;
        }""")

        if not elements_data:
            return "No interactive elements found on the current page."

        # Cache elements for index resolution
        controller.store_element_cache(elements_data)

        output_lines = [f"Interactive Elements on '{page.url}' (You can target elements by [index] e.g. browser_click('1') or browser_type('2', 'text')):\n"]
        for el in elements_data:
            type_str = f"({el['type']})" if el['type'] else ""
            line = f"[{el['index']}] <{el['tag']}{type_str}> {('Label/Text: ' + el['text']) if el['text'] else ''} | Selector: `{el['selector']}`"
            output_lines.append(line)

        return "\n".join(output_lines)
    except Exception as e:
        return f"Error scanning interactive elements: {e}"


@tool(name="browser_take_screenshot", description="Capture a screenshot of the visible browser window or webpage and save it locally.")
async def browser_take_screenshot(filename: Optional[str] = None) -> str:
    """Capture page screenshot and save to disk."""
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open."

        screenshot_dir = DATA_DIR / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            import time
            fname = f"browser_screenshot_{int(time.time())}.png"
        else:
            fname = filename if filename.endswith(".png") or filename.endswith(".jpg") else f"{filename}.png"

        save_path = screenshot_dir / fname
        await page.screenshot(path=str(save_path), full_page=False)
        logger.info(f"[BrowserControl] Screenshot saved to: '{save_path}'")
        return f"Screenshot successfully saved to: '{save_path}'."
    except Exception as e:
        return f"Error taking screenshot: {e}"


@tool(name="browser_fill_form_and_login", description="Automatically detect username/email and password fields on a webpage, fill in credentials, and click the Login/Sign-In button.")
async def browser_fill_form_and_login(
    username_or_email: str,
    password: str,
    url: Optional[str] = None,
    submit_button_text: Optional[str] = None
) -> str:
    """Automatically fills login credentials and submits the login form on the page."""
    try:
        page = await controller.ensure_page(headless=False)
        if url:
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url
            logger.info(f"[BrowserControl] Navigating to login URL: '{url}'...")
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(1000)

        # 1. Locate Username / Email input field
        user_selectors = [
            'input[autocomplete="username"]',
            'input[autocomplete="email"]',
            'input[type="email"]',
            'input[name*="user" i]',
            'input[name*="email" i]',
            'input[name*="login" i]',
            'input[id*="user" i]',
            'input[id*="email" i]',
            'input[id*="login" i]',
            'input[placeholder*="user" i]',
            'input[placeholder*="email" i]',
            'input[placeholder*="phone" i]',
            'input[placeholder*="roll" i]',
            'input[type="text"]'
        ]

        user_input = None
        for sel in user_selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                user_input = loc
                logger.info(f"[BrowserControl] Found username input with selector: '{sel}'")
                break

        if not user_input:
            return "Error: Could not locate a username or email input field on the page. Try inspecting the page with 'browser_get_interactive_elements'."

        await user_input.fill("")
        await user_input.fill(username_or_email)
        await page.wait_for_timeout(300)

        # 2. Locate Password field
        pass_selectors = [
            'input[type="password"]',
            'input[autocomplete="current-password"]',
            'input[name*="pass" i]',
            'input[id*="pass" i]',
            'input[placeholder*="pass" i]'
        ]

        pass_input = None
        for sel in pass_selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                pass_input = loc
                logger.info(f"[BrowserControl] Found password input with selector: '{sel}'")
                break

        if pass_input:
            await pass_input.fill("")
            await pass_input.fill(password)
            await page.wait_for_timeout(300)

        # 3. Locate & Click Login / Submit Button
        submit_btn = None
        if submit_button_text:
            safe_text = controller._escape_selector_text(submit_button_text)
            btn_loc = page.locator(f'button:has-text("{safe_text}"), input[value*="{safe_text}" i], a:has-text("{safe_text}")').first
            if await btn_loc.count() > 0 and await btn_loc.is_visible():
                submit_btn = btn_loc

        if not submit_btn:
            button_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Sign in")',
                'button:has-text("Sign In")',
                'button:has-text("Log in")',
                'button:has-text("Log In")',
                'button:has-text("Login")',
                'button:has-text("Submit")',
                'button:has-text("Next")',
                'button:has-text("Continue")',
                'button[name*="login" i]',
                'button[id*="login" i]'
            ]
            for btn_sel in button_selectors:
                loc = page.locator(btn_sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    submit_btn = loc
                    logger.info(f"[BrowserControl] Found submit button with selector: '{btn_sel}'")
                    break

        if submit_btn:
            await submit_btn.click()
        elif pass_input:
            await pass_input.press("Enter")
        else:
            await user_input.press("Enter")

        await page.wait_for_timeout(3000)
        new_title = await page.title()
        return f"Login credentials submitted for '{username_or_email}'.\nNew Page Title: '{new_title}'\nActive URL: {page.url}"
    except Exception as e:
        logger.error(f"[BrowserControl] browser_fill_form_and_login failed: {e}")
        return f"Error during automated login: {e}"


@tool(name="browser_list_tabs", description="List all open browser tabs/pages with their titles and URLs.")
async def browser_list_tabs() -> str:
    """List open tabs."""
    try:
        # Number the SAME filtered list browser_switch_tab indexes into
        # (open pages only). Enumerating raw _pages while skipping closed ones
        # produced gaps ([1],[3],...) so a displayed index no longer matched the
        # tab_index switch_tab expects.
        active_pages = [p for p in controller._pages if not p.is_closed()]
        if not active_pages:
            return "No open browser tabs."
        output = ["Open Browser Tabs:"]
        for idx, p in enumerate(active_pages, 1):
            title = await p.title()
            output.append(f"[{idx}] {title} | {p.url}" + (" (Active)" if p == controller._page else ""))
        return "\n".join(output)
    except Exception as e:
        return f"Error listing tabs: {e}"


@tool(name="browser_switch_tab", description="Switch the active focus to a specific open tab by tab index (1, 2, ...).")
async def browser_switch_tab(tab_index: int) -> str:
    """Switch active tab."""
    try:
        active_pages = [p for p in controller._pages if not p.is_closed()]
        if 1 <= tab_index <= len(active_pages):
            controller._page = active_pages[tab_index - 1]
            await controller._page.bring_to_front()
            title = await controller._page.title()
            return f"Switched to Tab [{tab_index}]: '{title}' ({controller._page.url})"
        return f"Error: Tab index {tab_index} out of range (1 to {len(active_pages)})."
    except Exception as e:
        return f"Error switching tab: {e}"


@tool(name="browser_back", description="Go back to the previous page in browser history.")
async def browser_back() -> str:
    """Navigate backwards in history."""
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open."
        await page.go_back()
        return f"Navigated back. Current URL: {page.url}"
    except Exception as e:
        return f"Error navigating back: {e}"


@tool(name="browser_forward", description="Go forward in browser history.")
async def browser_forward() -> str:
    """Navigate forward in history."""
    try:
        page = await controller.get_current_page()
        if not page:
            return "Error: No active browser window is open."
        await page.go_forward()
        return f"Navigated forward. Current URL: {page.url}"
    except Exception as e:
        return f"Error navigating forward: {e}"


@tool(name="browser_close", description="Close the visible web browser window and release resources.")
async def browser_close() -> str:
    """Close active browser session."""
    try:
        return await controller.close()
    except Exception as e:
        return f"Error closing browser: {e}"


@tool(name="browser_autonomous_task", description="Execute an autonomous, multi-step web browsing task end-to-end (like Antigravity's browser agent) given a user goal.")
async def browser_autonomous_task(goal: str, start_url: Optional[str] = None, max_steps: int = 6) -> str:
    """Autonomous goal-driven browser subagent loop."""
    from vision.cognitive.load_balancer import load_balancer
    
    logger.info(f"[BrowserAgent] Starting autonomous browser task: '{goal}' (start_url={start_url})")
    
    # 1. Initialize start page
    if start_url:
        await browser_open(start_url)
    else:
        page = await controller.get_current_page()
        if not page:
            await browser_open("https://www.google.com")

    history: List[str] = []
    
    for step in range(1, max_steps + 1):
        page = await controller.get_current_page()
        if not page:
            break

        current_url = page.url
        page_title = await page.title()
        interactive_elements_text = await browser_get_interactive_elements()
        content_sample = await browser_get_page_content(max_chars=1200)

        prompt = f"""You are an Antigravity Autonomous Web Browser SubAgent.
Goal: {goal}
Current Step: {step}/{max_steps}
Active Page: "{page_title}" ({current_url})

Interactive Elements on Page:
{interactive_elements_text}

Visible Content:
{content_sample}

Previous Actions Taken:
{chr(10).join(history) if history else 'None'}

Decide the next single action to take to achieve the user's goal.
Respond ONLY with a JSON object in this exact schema:
{{
    "thought": "Reasoning for the next step",
    "action": "click" | "type" | "press_key" | "scroll" | "navigate" | "done",
    "target": "Element index number like '1' or selector or URL (if navigate)",
    "text": "Text to type (if action is 'type')",
    "press_enter": true | false,
    "final_answer": "Final summary if action is 'done'"
}}
"""
        try:
            llm_resp = await load_balancer.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            raw_content = (llm_resp.get("content") or "").strip()
            
            # Extract JSON block
            json_match = re.search(r"\{.*\}", raw_content, re.DOTALL)
            if not json_match:
                history.append(f"Step {step}: Failed to parse JSON response.")
                continue

            action_data = json.loads(json_match.group(0))
            # Guard against present-but-None JSON values (e.g. "action": null),
            # which would make .lower()/str ops crash and be misreported as a
            # parse error.
            action = (action_data.get("action") or "").lower()
            thought = action_data.get("thought") or ""
            target = str(action_data.get("target") or "")
            text = action_data.get("text") or ""
            press_enter = bool(action_data.get("press_enter", False))
            final_answer = action_data.get("final_answer") or ""

            logger.info(f"[BrowserAgent] Step {step}: Action={action}, Target={target}, Thought={thought}")
            history.append(f"Step {step}: {action} (Target: {target}) -> {thought}")

            if action == "done":
                return f"Task Completed Successfully!\n\nGoal: {goal}\n\nResult:\n{final_answer or content_sample}"

            # Capture each sub-action's result string into history. Discarding it
            # let a failed click/type/navigate look like progress and inflated the
            # final "session finished" summary into false success; now the LLM
            # sees the real outcome on the next step and the log is faithful.
            elif action == "click":
                result = await browser_click(target)
                history.append(f"  ↳ click result: {result}")
                await asyncio.sleep(2)

            elif action == "type":
                result = await browser_type(target, text, press_enter=press_enter)
                history.append(f"  ↳ type result: {result}")
                await asyncio.sleep(2)

            elif action == "navigate":
                result = await browser_navigate(target)
                history.append(f"  ↳ navigate result: {result}")
                await asyncio.sleep(2)

            elif action == "scroll":
                result = await browser_scroll("down", 600)
                history.append(f"  ↳ scroll result: {result}")
                await asyncio.sleep(1)

            elif action == "press_key":
                result = await browser_press_key(target or "Enter")
                history.append(f"  ↳ press_key result: {result}")
                await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"[BrowserAgent] Step {step} error: {e}")
            history.append(f"Step {step} Error: {e}")

    # Fallback return after max steps
    final_content = await browser_get_page_content(max_chars=2000)
    return f"Autonomous browsing session finished ({max_steps} steps executed).\n\nGoal: {goal}\n\nAction History:\n" + "\n".join(history) + f"\n\nLatest Page Content:\n{final_content}"
