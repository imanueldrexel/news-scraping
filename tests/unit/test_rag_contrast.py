"""SYS-96 (#265): WCAG 2.2 AA contrast of the search page's colour tokens, light and dark.

Every colour in style.css is a token, so the pairs the stylesheet actually uses are
checked here: text >= 4.5:1 (1.4.3), control borders and the focus ring >= 3:1 (1.4.11).
The old page had #999 on white (2.85:1) and white on #34a853 (3.06:1)."""
import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parents[2] / "newscrawler" / "web" / "static" / "style.css").read_text(encoding="utf-8")

TEXT_PAIRS = [  # (foreground, background) as used in style.css
    ("ink", "bg"), ("ink", "surface"), ("ink", "surface-2"),
    ("ink-2", "bg"), ("ink-2", "surface"), ("ink-2", "surface-2"),
    ("accent-ink", "accent"),
    ("accent", "bg"), ("accent", "surface"), ("accent", "accent-soft"),
    ("link", "bg"), ("link", "surface"),
    ("warn-ink", "warn-bg"),
]
NON_TEXT_PAIRS = [
    ("control-line", "surface"), ("control-line", "bg"),
    ("focus", "bg"), ("focus", "surface"),
    ("accent", "bg"),
]


def _block(selector_regex):
    m = re.search(selector_regex + r"\s*\{(.*?)\}", CSS, re.S)
    assert m, f"no block for {selector_regex}"
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", m.group(1)))


LIGHT = _block(r"(?m)^:root")
DARK = _block(r':root\[data-theme="dark"\]')
DARK_MEDIA = _block(r':root:not\(\[data-theme="light"\]\)')


def _luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_formula_matches_the_ticket():
    assert round(contrast("#999999", "#ffffff"), 2) == 2.85
    assert round(contrast("#ffffff", "#34a853"), 2) == 3.06


def test_both_dark_blocks_agree_and_define_every_light_token():
    assert DARK == DARK_MEDIA
    assert set(DARK) == set(LIGHT), "a token without a dark value reads in one theme only"


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("fg, bg", TEXT_PAIRS)
def test_text_contrast(theme, fg, bg):
    tokens = LIGHT if theme == "light" else DARK
    ratio = contrast(tokens[fg], tokens[bg])
    assert ratio >= 4.5, f"{theme}: --{fg} on --{bg} is {ratio:.2f}:1"


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("fg, bg", NON_TEXT_PAIRS)
def test_non_text_contrast(theme, fg, bg):
    tokens = LIGHT if theme == "light" else DARK
    ratio = contrast(tokens[fg], tokens[bg])
    assert ratio >= 3.0, f"{theme}: --{fg} against --{bg} is {ratio:.2f}:1"


def test_no_literal_colour_outside_the_token_blocks():
    rules = re.sub(r"(?m)^:root\s*\{.*?\}|:root\[data-theme=\"dark\"\]\s*\{.*?\}|"
                   r"@media \(prefers-color-scheme: dark\)\s*\{.*?\}\s*\}", "",
                   re.sub(r"/\*.*?\*/", "", CSS, flags=re.S), flags=re.S)
    assert re.findall(r"#[0-9a-fA-F]{3,6}\b", rules) == []


def test_focus_is_visible_on_every_control():
    assert re.search(r":focus-visible\s*\{[^}]*outline:\s*3px solid var\(--focus\)", CSS)


def test_the_search_indicator_is_hidden_at_rest():
    # 2026-10-07 screenshot: `.pending { display: flex }` on the same element overrode
    # `.search-status { display: none }`, so "Mencari artikel…" showed permanently.
    assert re.search(r"\.search-status\s*\{\s*display:\s*none", CSS)
    html = (Path(__file__).resolve().parents[2] / "newscrawler" / "web" / "templates" / "index.html").read_text(
        encoding="utf-8")
    indicator = re.search(r'<[^>]*id="search-status"[^>]*>', html).group(0)
    for cls in re.search(r'class="([^"]*)"', indicator).group(1).split():
        if cls == "search-status":
            continue
        rule = re.search(rf"(?m)^\.{cls}\s*\{{([^}}]*)\}}", CSS)
        assert not (rule and "display" in rule.group(1)), f".{cls} sets display on the indicator"
