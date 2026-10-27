"""Headless Chrome via Selenium (§5.2).

No current adapter needs it (Phase 0 found JSON or server-rendered data for all six
sources), but it stays available for sources whose listings need JavaScript. The
driver is created lazily on first use and shared for the whole run.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

log = logging.getLogger(__name__)


class Browser:
    def __init__(
        self,
        *,
        user_agent: str,
        proxy_url: str | None,
        page_load_timeout: float = 30.0,
        chrome_binary: str | None = None,
        chromedriver: str | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.proxy_url = proxy_url
        self.page_load_timeout = page_load_timeout
        # The image ships Debian's chromium + chromedriver; locally Selenium Manager
        # resolves a driver when these are unset.
        self.chrome_binary = chrome_binary or os.environ.get("JOBS_CHROME_BIN")
        self.chromedriver = chromedriver or os.environ.get("JOBS_CHROMEDRIVER")
        self._driver: WebDriver | None = None

    @property
    def driver(self) -> WebDriver:
        if self._driver is None:
            from selenium import webdriver

            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument(f"--user-agent={self.user_agent}")
            if self.proxy_url:
                # Credential-free forwarding proxy; it adds upstream auth (§5.1).
                options.add_argument(f"--proxy-server={self.proxy_url}")
            if self.chrome_binary:
                options.binary_location = self.chrome_binary
            service = webdriver.ChromeService(executable_path=self.chromedriver) if self.chromedriver else None
            self._driver = webdriver.Chrome(options=options, service=service)
            self._driver.set_page_load_timeout(self.page_load_timeout)
            log.info("chrome started", extra={"proxy": bool(self.proxy_url)})
        return self._driver

    def page_source(self, url: str, wait_css: str, timeout: float = 20.0) -> str:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as ec
        from selenium.webdriver.support.ui import WebDriverWait

        driver = self.driver
        driver.get(url)
        WebDriverWait(driver, timeout).until(ec.presence_of_element_located((By.CSS_SELECTOR, wait_css)))
        return driver.page_source

    def quit(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            finally:
                self._driver = None
