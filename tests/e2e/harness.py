"""Browser harness for the Streamlit app.

Real Chromium, real widget interaction, real screenshots. No mocking: the
screenshots in the testing report are of the running application.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

DEMO = {
    "faculty": ("a.verma@iet.example.edu", "faculty123"),
    "student": ("CSE-3A-01", "student123"),
    "admin": ("registrar", "admin123"),
}


class UIError(AssertionError):
    pass


@dataclass
class Scenario:
    id: str
    title: str
    role: str                     # faculty | student | admin | none
    case: str                     # base | normal | edge
    steps: list[str]
    expected: str
    run: object                   # callable(ui) -> str  (the observation)
    requirement: str = ""
    screenshot_strategy: str = "viewport"
    tags: list[str] = field(default_factory=list)


class UI:
    def __init__(self, page: Page, shot_dir: Path, base_url: str = "http://localhost:8501"):
        self.page = page
        self.shot_dir = Path(shot_dir)
        self.base_url = base_url
        self.console_errors: list[str] = []

    # -------------------------------------------------------------- plumbing
    def _watch(self):
        self.page.on("console", self._on_console)
        self.page.on("pageerror", lambda e: self.console_errors.append(str(e)))

    def _on_console(self, message):
        if message.type == "error":
            self.console_errors.append(message.text)

    def goto(self):
        self.page.goto(self.base_url, wait_until="networkidle", timeout=60000)
        self.settle(1800)

    def settle(self, ms: int = 1200):
        """Wait for Streamlit to finish its script run."""
        deadline = time.time() + 25
        while time.time() < deadline:
            status = self.page.locator('div[data-testid="stStatusWidget"]')
            if status.count() == 0 or not status.first.is_visible():
                break
            time.sleep(0.2)
        self.page.wait_for_timeout(ms)

    def text(self) -> str:
        return self.page.inner_text("body")

    # -------------------------------------------------------------- widgets
    def sign_in(self, role: str, login: str | None = None, password: str | None = None):
        if role == "none":
            return
        default_login, default_password = DEMO[role]
        login = login or default_login
        password = password or default_password
        self.page.get_by_label("Role", exact=True).first.click()
        self.page.wait_for_timeout(400)
        self.page.get_by_role("option", name=role, exact=True).click()
        self.settle(1400)
        self.page.get_by_label("Login", exact=True).first.fill(login)
        self.page.get_by_label("Password", exact=True).first.fill(password)
        self.page.get_by_role("button", name="Sign in").click()
        self.settle(2200)
        if "Navigation" not in self.text():
            raise UIError(f"sign-in as {role} did not reach the shell")

    def sign_out(self):
        if self.page.get_by_role("button", name="Sign out").count():
            self.page.get_by_role("button", name="Sign out").click()
            self.settle(1600)

    def nav(self, label: str):
        self.page.get_by_text(label, exact=True).first.click()
        self.settle(2000)
        if label.lower() not in self.text().lower():
            raise UIError(f"navigation to {label!r} did not render")

    def set_date(self, iso: str, label: str = "Date"):
        """Streamlit's date field is a segmented control: month, day, year."""
        year, month, day = iso.split("-")
        for part, value in (("month", str(int(month))), ("day", str(int(day))), ("year", year)):
            field = self.page.get_by_role("spinbutton", name=f"{part}, {label}").first
            field.click()
            self.page.keyboard.press("Control+A")
            self.page.keyboard.type(value)
            self.page.wait_for_timeout(200)
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(900)

    def choose(self, label: str, option: str, index: int = 0):
        combo = self.page.get_by_label(label, exact=True).nth(index)
        combo.click()
        self.page.wait_for_timeout(500)
        try:
            self.page.get_by_role("option", name=option, exact=True).first.click()
        except PlaywrightTimeout:
            self.page.get_by_role("option", name=re.compile(f"^{re.escape(option)}")).first.click()
        self.settle(1400)

    def count(self, label: str) -> int:
        return self.page.get_by_label(label, exact=True).count()

    def choose_nth(self, label: str, index: int, option: str):
        self.page.get_by_label(label, exact=True).nth(index).click()
        self.page.wait_for_timeout(500)
        self.page.get_by_role("option", name=option, exact=True).first.click()
        self.settle(1400)

    def fill(self, label: str, value: str, index: int = 0):
        self.page.get_by_label(label, exact=True).nth(index).fill(value)
        self.settle(500)

    def number(self, label: str, value: str, index: int = 0):
        self.fill(label, value, index=index)

    def click(self, label: str, exact: bool = True):
        self.page.get_by_role("button", name=label, exact=exact).first.click()
        self.settle(2200)

    def click_text(self, text: str):
        self.page.get_by_text(text, exact=True).first.click()
        self.settle(1800)

    def expand(self, label: str):
        self.page.get_by_text(label, exact=False).first.click()
        self.settle(900)

    # -------------------------------------------------------------- asserts
    def expect(self, needle: str, where: str = "page"):
        body = self.text()
        if needle.lower() not in body.lower():
            raise UIError(f"expected {needle!r} on the {where}; not found")

    def expect_absent(self, needle: str):
        if needle.lower() in self.text().lower():
            raise UIError(f"expected {needle!r} to be absent, but it is on the page")

    def expect_any(self, needles):
        body = self.text().lower()
        for needle in needles:
            if needle.lower() in body:
                return needle
        raise UIError(f"none of {needles!r} appeared")

    def expect_count(self, fragment: str, minimum: int = 1):
        actual = self.text().lower().count(fragment.lower())
        if actual < minimum:
            raise UIError(f"expected at least {minimum} occurrence(s) of {fragment!r}, found {actual}")

    # -------------------------------------------------------------- capture
    def shot(self, name: str, full: bool = False) -> str:
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        path = self.shot_dir / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=full)
        return str(path)
