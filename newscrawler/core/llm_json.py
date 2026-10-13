"""Ask a model for JSON, check the answer, ask once more with the reason (DBT-73 #345, ADR-017).

The newsletter asks the model for JSON in three places -- a story's summary
(SYS-82), the editor's picks (SYS-83) and a story's arc (SYS-148) -- and each
answer is held to rules a function checks. They share one loop:

    ask -> check -> refused? ask again once, with the refusal's detail -> None

`ask_json` runs it and returns an `Outcome`: the checked value (None when the
answer was refused twice), every refusal's reason in order, the number of
calls, and the raw answers (what a replay reads, instead of patching `parse`).

A provider failure is the caller's choice (`on_error`), because the two uses
differ on purpose:
- "raise": the summary lets it pass (the generator counts failures in a row
  and stops after NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS); the refusals
  collected before it ride on the exception as `.refusals`.
- "retry": the editor counts it as reason "error" and asks again without a
  refusal detail; a quota stops it with reason "quota" and no further call.
A daily quota (`QuotaExhausted`) under "raise" propagates, with `.refusals` too.
"""
import json
import logging
import re
from typing import Any, Callable, List, NamedTuple, Optional, TypeVar

from newscrawler.core.summarizer import QuotaExhausted, SummarizerError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

RETRY = "\n\nJawaban sebelumnya ditolak: {detail}. Perbaiki dan balas HANYA dengan JSON valid."

T = TypeVar("T")


class Rejected(Exception):
    """An answer that breaks a rule. `reason` is a short tag counted in the
    stats ("json", "length", "number", ...); `detail` is the one line the retry
    tells the model."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class Outcome(NamedTuple):
    value: Any                  # the checked answer, or None
    reasons: List[str]          # every refusal (and, under "retry", "error"/"quota"), in order
    calls: int                  # model calls made (a failed call counts)
    answers: List[str]          # the raw answers received, in order


def json_object(answer: Optional[str]) -> dict:
    """The JSON object in a model's answer (possibly fenced or surrounded by
    text), or Rejected("json"). Only a {...} span is parsed, so the value is a dict."""
    return json_value(answer, r"\{.*\}")


def json_value(answer: Optional[str], pattern: str = r"\{.*\}|\[.*\]") -> Any:
    """The JSON object or list in a model's answer, or Rejected("json")."""
    match = re.search(pattern, answer or "", re.DOTALL)
    if not match:
        raise Rejected("json", "jawaban bukan JSON")
    try:
        return json.loads(match.group(0))
    except ValueError:
        raise Rejected("json", "JSON tidak valid")


def ask_json(summarizer, prompt: str, check: Callable[[str, int], T], *, retries: int = 1,
             on_error: str = "raise", label: str = "Answer") -> Outcome:
    """Ask, check, and ask again up to `retries` times after a refusal (with
    RETRY and the refusal's detail appended to `prompt`). `check(answer,
    attempt)` returns the value or raises Rejected; `attempt` is 0 for the
    first answer, so a retry may be checked more leniently. `on_error`:
    "raise" or "retry" (module docstring). `label` names the call in the log."""
    if on_error not in ("raise", "retry"):
        raise ValueError(f"on_error must be 'raise' or 'retry', not {on_error!r}")
    reasons: List[str] = []
    answers: List[str] = []
    calls = 0
    ask = prompt
    for attempt in range(retries + 1):
        calls += 1
        try:
            answer = summarizer.summarize(ask)
        except QuotaExhausted as e:
            if on_error == "raise":
                e.refusals = list(reasons)
                raise
            reasons.append("quota")
            break
        except SummarizerError as e:
            if on_error == "raise":
                e.refusals = list(reasons)
                raise
            reasons.append("error")
            logger.warning(f"{label} call failed: {e}")
            ask = prompt
            continue
        answers.append(answer)
        try:
            return Outcome(check(answer, attempt), reasons, calls, answers)
        except Rejected as r:
            reasons.append(r.reason)
            again = attempt < retries
            logger.info(f"{label} refused{', asking again' if again else ''} ({r})")
            ask = prompt + RETRY.format(detail=r.detail)
    return Outcome(None, reasons, calls, answers)
