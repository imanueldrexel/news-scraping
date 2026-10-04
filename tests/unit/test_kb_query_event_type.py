"""SYS-77 (#229): `kb_query --event-type` takes one of the closed list, so a typo or the old
"policy" is an argparse error with the choices, not a silent empty result."""
import pytest

from newscrawler.core.knowledge_extractor import EVENT_TYPES
from newscrawler.tools import kb_query


def _parse(argv):
    return kb_query.build_parser().parse_args(argv)


@pytest.mark.parametrize("value", EVENT_TYPES)
def test_every_listed_event_type_is_accepted(value):
    assert _parse(["--ticker", "BBCA", "--event-type", value]).event_type == value


def test_case_does_not_matter():
    assert _parse(["--ticker", "BBCA", "--event-type", "Earnings_Report"]).event_type == "earnings_report"


@pytest.mark.parametrize("value", ["policy", "earnings", "pelantikan menteri", ""])
def test_a_value_outside_the_list_is_an_error_that_names_the_choices(value, capsys):
    with pytest.raises(SystemExit) as raised:
        _parse(["--ticker", "BBCA", "--event-type", value])
    assert raised.value.code == 2
    assert "policy_announcement" in capsys.readouterr().err


def test_no_event_type_means_no_filter():
    assert _parse(["--ticker", "BBCA"]).event_type is None


def test_the_help_lists_the_vocabulary():
    text = kb_query.build_parser().format_help()
    assert all(v in text for v in EVENT_TYPES)
