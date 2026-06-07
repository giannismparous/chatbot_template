from __future__ import annotations

from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser


class RobotsChecker:
    def __init__(self, *, user_agent: str) -> None:
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}

    def can_fetch(self, url: str) -> tuple[bool, str | None]:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False, "invalid_url"
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._parsers.get(origin)
        if origin not in self._parsers:
            parser = RobotFileParser()
            robots_url = urljoin(origin, "/robots.txt")
            try:
                parser.set_url(robots_url)
                parser.read()
            except Exception:
                self._parsers[origin] = None
                return True, None
            self._parsers[origin] = parser
        if parser is None:
            return True, None
        try:
            allowed = parser.can_fetch(self._user_agent, url)
        except Exception:
            return True, None
        if allowed:
            return True, None
        return False, "blocked_by_robots"
