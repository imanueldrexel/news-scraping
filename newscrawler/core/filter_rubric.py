"""SYS-36 (#120): the written definition of "news-worthy" and the exact prompt
used to label the gold set (`tests/fixtures/filter_gold.jsonl`).

Owner decision 2026-09-20 (PRD scope amendment): the product keeps everything
news-worthy, not only finance. This module is the single source of truth for
that boundary -- the labeller (`scripts/label_filter_gold.py`), the weekly
drift audit (OPS-18 #123) and the class list the classifier is trained on
(SYS-37 #121) all import it. Change the rubric here, then re-label; never
paraphrase it in a script.

Amended 2026-09-21 (SYS-46 #142, owner decision from the SYS-36 hand check):
school/campus regulations and guidance are soft even from a ministry, and a
celebrity's own criminal case is soft unless a public institution or policy is
the subject. Every gold label was re-derived under this wording.
"""
from typing import List

# The topic classes, in the order the newsletter renders them (SYS-40): the
# five finance topics first, then the rest, then `soft` for not-news.
TOPICS_FINANCE: List[str] = [
    "markets",            # equities, bonds, forex, crypto prices and flows, IHSG, rupiah
    "macro_policy",       # BI/OJK/Kemenkeu policy, rates, inflation, GDP, budget, tax, tariffs
    "corporate",          # a company's results, deals, expansion, layoffs, leadership, IPO
    "commodities_energy", # oil, gas, coal, nickel, palm oil, food prices, fuel/LPG supply
    "consumer",           # retail, e-commerce, property, transport fares, tourism business, UMKM
]
TOPICS_NEWS: List[str] = [
    "politics_government",  # elections, parties, DPR, cabinet, governors, government programmes
    "law_crime",            # police, courts, KPK, prosecutions, crime incidents, corruption cases (SYS-46: not a celebrity's own case)
    "disaster_accident",    # floods, quakes, fires, crashes, epidemics as events
    "international",        # foreign affairs and events abroad (unless clearly economy -> finance topic)
    "tech_science",         # technology and science developments as events (launches, discoveries, regulation)
    "health_education",     # health/education policy, outbreaks, university/exam-system news (SYS-46: not school rules)
    "other_news",           # news-worthy but none of the above (obituaries, religion-as-news, culture events)
]
TOPIC_SOFT = "soft"
TOPICS: List[str] = TOPICS_FINANCE + TOPICS_NEWS + [TOPIC_SOFT]

RUBRIC_TEXT = """\
NEWS-WORTHY (is_news = true): a reported, time-bound event or development
with public significance -- politics and government, economy/business/markets,
law and crime, disasters and accidents, international affairs, science/tech
DEVELOPMENTS, health OUTBREAKS and health/education POLICY at the level of
budgets, funding, system-wide structural change (a curriculum overhaul, a
national exam abolished), scandals, investigations, strikes or incidents;
infrastructure; obituaries of public figures. Kemenag's haji quota is news
(other_news or politics_government). A dengue outbreak is news
(health_education). A minister on mining revenue sharing, fuel prices or
tariffs is news (macro_policy). An economic-policy story is news even when
the actor is a politician. Sports BUSINESS (a club's finances, a
broadcast-rights deal) is news; the match is not. A police or prosecutor
corruption case, an official charged, or a court ruling that changes the law
is news (law_crime) whoever else is named in it.

NOT NEWS-WORTHY (is_news = false, topic = soft): evergreen, service or
lifestyle content with no event -- recipes (Resep ...), doa/prayer guides,
daily religious reflections, khutbah, horoscopes/zodiak, tips and how-tos,
listicles (7 Gaya OOTD ..., 5 Zodiak yang ...), celebrity gossip/relationships/
pregnancies/fashion/OOTD, product reviews and gadget specs, fiction and poetry
([PUISI] ...), quizzes, travel guides, health tips (Manfaat ...), kata-kata
bijak, advertorials and siaran pers reprints, song lyrics and chords, TV
synopses, AND SPORTS (results, transfers, Persib/Timnas coverage -- owner
decision: out). ALSO SOFT (owner decision 2026-09-21): school and campus
regulations and guidance -- phone/device rules, uniforms, attendance,
schedules, admission and exam procedures, study tips -- even when a ministry
issues them ("Kemenag Batasi Penggunaan HP di Sekolah" is soft); and a
celebrity's OWN criminal case -- arrest, suspect status, trial, KDRT, drugs --
which is entertainment coverage ("Rizky Billar Ditetapkan Tersangka KDRT" is
soft) unless the story's subject is a public institution or a policy.

TIE-BREAK: would a national desk editor put it in the front section, or in
the lifestyle / entertainment / sports supplement?

TOPIC (for is_news = true), pick exactly one:
  markets            - stock/bond/forex/crypto prices, IHSG, rupiah, capital flows, an emiten's shares
  macro_policy       - Bank Indonesia, OJK, Kemenkeu, rates, inflation, GDP, APBN, taxes, tariffs, trade policy
  corporate          - a specific company: results, deals, M&A, expansion, layoffs, leadership, IPO, products as business
  commodities_energy - oil, gas, coal, minerals, palm oil, rice and food prices, fuel/LPG/electricity supply
  consumer           - retail, e-commerce, property, transport fares, tourism business, UMKM, consumer finance
  politics_government- elections, parties, DPR, cabinet, regional heads, government programmes not mainly economic
  law_crime          - police, prosecutors, courts, KPK, crimes and their investigation (not a celebrity's own case: soft)
  disaster_accident  - floods, earthquakes, fires, transport accidents, epidemics as events
  international      - events abroad and foreign affairs, unless the story is mainly economic (then a finance topic)
  tech_science       - technology/science developments: launches, regulation, discoveries, cyber incidents
  health_education   - health/education policy and funding, outbreaks, university and exam-SYSTEM news (not school rules: soft)
  other_news         - news-worthy but none of the above (obituaries, religion as news, culture as news)
  soft               - ONLY when is_news = false
When a story is both economic and political (a minister announcing a tax),
prefer the finance topic. When only a headline is given, label from the
headline alone; do not guess a body.
"""

# The exact labelling prompt. `{rows_json}` is a JSON array of
# {"id": <int>, "headline": <str>, "body_head": <str or null>}.
LABEL_PROMPT_TEMPLATE = """\
You are labelling Indonesian news articles for a news aggregator. Apply this rubric exactly:

{rubric}

For EACH row below, decide is_news (true/false) and topic (one of: {topics}).
Rows with body_head = null have only a headline: label from the headline.

Return ONLY a JSON array, one object per input row, same order, shape:
[{{"id": <id>, "is_news": true|false, "topic": "<topic>"}}, ...]

Rows:
{rows_json}
"""


def build_label_prompt(rows_json: str) -> str:
    return LABEL_PROMPT_TEMPLATE.format(rubric=RUBRIC_TEXT, topics=", ".join(TOPICS), rows_json=rows_json)


def is_valid_label(is_news, topic) -> bool:
    """A label is consistent when topic is a known class and `soft` is used
    if and only if is_news is false."""
    if not isinstance(is_news, bool) or topic not in TOPICS:
        return False
    return (topic == TOPIC_SOFT) == (not is_news)
