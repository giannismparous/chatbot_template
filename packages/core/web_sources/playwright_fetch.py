from __future__ import annotations

from typing import Callable

from packages.core.web_sources.models import PLAYWRIGHT_INSTALL_HINT
from packages.core.web_sources.validation import same_registrable_domain

RenderFn = Callable[[str], str]


class PlaywrightNotAvailableError(RuntimeError):
    pass


class PlaywrightTimeoutError(RuntimeError):
    pass


class PlaywrightRenderError(RuntimeError):
    pass


def render_page_with_browser(
    browser,
    url: str,
    *,
    wait_until: str,
    wait_selector: str | None,
    timeout_seconds: float,
    user_agent: str,
    render_fn: RenderFn | None = None,
) -> tuple[str, str]:
    if render_fn is not None:
        return render_fn(url), url

    timeout_ms = int(timeout_seconds * 1000)
    context = browser.new_context(user_agent=user_agent)
    try:
        page = context.new_page()
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            final_url = page.url
            if not same_registrable_domain(final_url, url):
                raise PlaywrightRenderError("Navigation left the allowed domain.")
            return page.content(), final_url
        except Exception as exc:
            exc_name = type(exc).__name__
            if exc_name == "TimeoutError" or "Timeout" in exc_name:
                raise PlaywrightTimeoutError(str(exc)) from exc
            raise PlaywrightRenderError(str(exc)) from exc
    finally:
        context.close()


def check_playwright_available() -> str | None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return PLAYWRIGHT_INSTALL_HINT
    return None
