"""Indeed scraping helpers."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Sequence
from urllib.parse import urlencode

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import Page, async_playwright

try:
    from plyer import notification
except ImportError:  # pragma: no cover - optional local desktop integration
    notification = None

INDEED_BASE_URL = "https://www.indeed.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


class IndeedScrapeBlockedError(RuntimeError):
    """Raised when Indeed blocks scraping with an anti-bot challenge."""


def _normalize_keywords(keywords: str | Sequence[str]) -> list[str]:
    if isinstance(keywords, str):
        cleaned = keywords.strip()
        return [cleaned] if cleaned else []

    return [keyword.strip() for keyword in keywords if keyword and keyword.strip()]


def _build_search_url(keyword: str, location: str, start: int = 0) -> str:
    params = {"q": keyword, "l": location}
    if start:
        params["start"] = str(start)
    return f"{INDEED_BASE_URL}/jobs?{urlencode(params)}"


async def _human_delay() -> None:
    await asyncio.sleep(random.uniform(2, 3))


async def _homepage_delay() -> None:
    await asyncio.sleep(random.uniform(3, 4))


async def _move_mouse_randomly(page: Page, moves: int | None = None) -> None:
    move_count = moves or random.randint(2, 4)
    for _ in range(move_count):
        await page.mouse.move(
            random.randint(80, 1280),
            random.randint(80, 720),
            steps=random.randint(12, 30),
        )
        await asyncio.sleep(random.uniform(0.15, 0.45))


async def _hide_automation_signals(page: Page) -> None:
    await page.evaluate(
        """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """
    )


async def _visit_homepage(page: Page) -> None:
    await _move_mouse_randomly(page)
    await page.goto(
        INDEED_BASE_URL,
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    await _hide_automation_signals(page)
    await _move_mouse_randomly(page)
    await _homepage_delay()


async def _is_challenge_page(page: Page) -> bool:
    try:
        title = (await page.title()).strip().lower()
    except PlaywrightError:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        title = (await page.title()).strip().lower()

    return "just a moment" in title or "are you a robot" in title


def _send_captcha_notification() -> None:
    if notification is None:
        return

    notification.notify(
        title="Indeed CAPTCHA detected",
        message="CAPTCHA detected on Indeed - please solve it in the browser window",
        timeout=10,
    )


async def _wait_for_captcha_resolution(page: Page, timeout_seconds: int = 60) -> None:
    if not await _is_challenge_page(page):
        return

    _send_captcha_notification()
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(2)
        if not await _is_challenge_page(page):
            return

    raise IndeedScrapeBlockedError(
        "Indeed challenge page did not clear within 60 seconds."
    )


async def _wait_for_results(page: Page) -> None:
    selector = "a.tapItem, a[href*='/viewjob?jk='], a[href*='clk?jk=']"
    try:
        await page.wait_for_selector(selector, timeout=15_000)
        return
    except PlaywrightTimeoutError:
        await _wait_for_captcha_resolution(page)
        await page.wait_for_selector(selector, timeout=15_000)


async def _load_results_page(
    page: Page,
    *,
    keyword: str,
    location: str,
    start: int,
) -> None:
    await _human_delay()
    await _move_mouse_randomly(page)
    await page.goto(
        _build_search_url(keyword=keyword, location=location, start=start),
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    await _hide_automation_signals(page)
    await _move_mouse_randomly(page)

    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass

    await _wait_for_captcha_resolution(page)
    await _wait_for_results(page)


async def _extract_jobs_from_page(page: Page) -> list[dict]:
    return await page.eval_on_selector_all(
        "a.tapItem, a[href*='/viewjob?jk='], a[href*='clk?jk=']",
        """(anchors) => {
            const cleanText = (value) => (value || "").replace(/\\s+/g, " ").trim();
            const jobs = [];
            const seen = new Set();

            for (const anchor of anchors) {
                const href = anchor.getAttribute("href") || "";
                const absoluteUrl = new URL(anchor.href, window.location.origin).toString();
                const idMatch = href.match(/jk=([a-zA-Z0-9]+)/) || absoluteUrl.match(/jk=([a-zA-Z0-9]+)/);
                const uniqueId = idMatch ? idMatch[1] : absoluteUrl;

                if (!uniqueId || seen.has(uniqueId)) {
                    continue;
                }

                seen.add(uniqueId);

                const card = anchor.matches("a.tapItem")
                    ? anchor
                    : anchor.closest(
                        "a.tapItem, div.cardOutline, div.job_seen_beacon, div.slider_container, article, li, td, div"
                    ) || anchor.parentElement;

                const title = cleanText(
                    anchor.getAttribute("aria-label") ||
                    anchor.querySelector("span[title]")?.getAttribute("title") ||
                    anchor.textContent
                );
                const company = cleanText(
                    card?.querySelector('[data-testid="company-name"]')?.textContent ||
                    card?.querySelector(".companyName")?.textContent ||
                    ""
                );
                const location = cleanText(
                    card?.querySelector('[data-testid="text-location"]')?.textContent ||
                    card?.querySelector(".companyLocation")?.textContent ||
                    ""
                );
                const description = cleanText(
                    card?.querySelector('[data-testid="job-snippet"]')?.textContent ||
                    card?.querySelector(".job-snippet")?.textContent ||
                    ""
                );

                if (!title || !company) {
                    continue;
                }

                jobs.push({
                    title,
                    company,
                    location,
                    url: absoluteUrl,
                    description,
                    source: "indeed"
                });
            }

            return jobs;
        }""",
    )


async def scrape_indeed(
    keywords: str | Sequence[str] = "",
    location: str = "remote",
    max_pages: int = 1,
) -> list[dict]:
    """Scrape Indeed search result pages for one or more keyword queries."""
    normalized_keywords = _normalize_keywords(keywords)
    if not normalized_keywords:
        return []

    unique_jobs: dict[str, dict] = {}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--start-maximized",
            ],
        )
        context = await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            locale="en-US",
            viewport={"width": 1366, "height": 768},
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        page = await context.new_page()

        try:
            await _visit_homepage(page)
            for keyword in normalized_keywords:
                for page_index in range(max_pages):
                    start = page_index * 10
                    await _load_results_page(
                        page,
                        keyword=keyword,
                        location=location,
                        start=start,
                    )

                    for job in await _extract_jobs_from_page(page):
                        unique_jobs[job["url"]] = job
        finally:
            await context.close()
            await browser.close()

    return list(unique_jobs.values())
