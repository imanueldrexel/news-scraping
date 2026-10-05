"""Fakes shared by the newsletter tests (SYS-82/SYS-83).

The newsletter sends a summarizer three kinds of prompt: SYS-67's story
grouping, SYS-82's per-story summary and SYS-83's editor pass. `prompt_kind`
tells them apart, `story_answer` writes a valid summary for a summary prompt
(built from the prompt's own first headline, so every number in it is in the
input), and `FakeNewsroom` answers each kind from its own script.
"""
import json
import re

VALID = object()          # a script item: "answer this summary prompt validly"


def prompt_kind(prompt: str) -> str:
    if "Kamu pemimpin redaksi" in prompt:
        return "editor"
    if "Kamu redaktur briefing" in prompt:
        return "story"
    if "Kelompokkan nomor" in prompt:
        return "group"
    raise AssertionError(f"unknown prompt: {prompt[:80]!r}")


def shown_articles(prompt: str):
    """[(index, outlet, headline)] of a summary prompt's ARTIKEL block."""
    block = prompt.rsplit("ARTIKEL\n", 1)[1]
    return [(int(i), outlet, headline) for i, outlet, headline in
            re.findall(r"^\[(\d+)\] (.+?) — (.*)$", block, re.MULTILINE)]


def story_answer(prompt: str, **override) -> str:
    """A valid answer: every article terkait, judul/inti/sekilas from the first headline."""
    arts = shown_articles(prompt)
    words = arts[0][2].split()
    data = {"judul": " ".join(words[:10]), "inti": " ".join(words[:25]), "poin": [], "mengapa_penting": "",
            "sekilas": " ".join(words[:15]), "terkait": [i for i, _, _ in arts], "tidak_terkait": []}
    data.update(override)
    return json.dumps(data)


class FakeNewsroom:
    """A summarizer whose answers come from one script per prompt kind. A
    script item is a string (the answer), an exception (raised), VALID (a valid
    story answer) or a callable(prompt) -> answer. An exhausted story script
    answers VALID; an exhausted editor script answers what is not JSON (so the
    edition takes its deterministic fallback); an exhausted grouping script
    keeps every cluster on its own."""
    name = "fake-model"

    def __init__(self, story=(), editor=(), group=()):
        self.scripts = {"story": list(story), "editor": list(editor), "group": list(group)}
        self.prompts = {"story": [], "editor": [], "group": []}

    @property
    def calls(self) -> int:
        return sum(len(p) for p in self.prompts.values())

    def summarize(self, prompt):
        kind = prompt_kind(prompt)
        self.prompts[kind].append(prompt)
        script = self.scripts[kind]
        if script:
            item = script.pop(0)
        else:
            item = {"story": VALID, "editor": "bukan json", "group": None}[kind]
        if item is None:     # grouping: every cluster its own story
            n = len(re.findall(r"^\d+: ", prompt, re.MULTILINE))
            return json.dumps({"grup": [[i] for i in range(n)]})
        if isinstance(item, Exception):
            raise item
        if item is VALID:
            return story_answer(prompt)
        if callable(item):
            return item(prompt)
        return item
