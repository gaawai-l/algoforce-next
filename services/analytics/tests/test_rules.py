from typing import get_args

import pytest

from wheelhouse_service import rules
from wheelhouse_service.rules import ALL_RULES, View, parse_rules, rules_for_view
from wheelhouse_service.settings import Settings


def test_all_rules_are_o1_to_o6():
    assert frozenset({"O1", "O2", "O3", "O4", "O5", "O6"}) == ALL_RULES


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Unset or empty means the default, every rule on: compose can produce "" by accident.
        (None, ALL_RULES),
        ("", ALL_RULES),
        ("   ", ALL_RULES),
        ("O1,O2", {"O1", "O2"}),
        ("o1,O5", {"O1", "O5"}),
        (" O3 ,\to4 ", {"O3", "O4"}),
        ("O2,o2, O2", {"O2"}),
        ("O1,O2,O3,O4,O5,O6", ALL_RULES),
        # `v1` alone turns every rule off.
        ("v1", frozenset()),
        (" V1 ", frozenset()),
        ("v1,V1", frozenset()),
    ],
)
def test_parse_rules(text: str | None, expected: frozenset[str]):
    assert parse_rules(text) == expected


@pytest.mark.parametrize("text", ["v1,O2", "O2, v1", "V1,o6"])
def test_parse_rules_rejects_v1_with_other_rules(text: str):
    with pytest.raises(ValueError, match="v1"):
        parse_rules(text)


@pytest.mark.parametrize("text", ["O7", "O0", "O1,X", "all", "none", "1", "O 1"])
def test_parse_rules_rejects_unknown_values(text: str):
    with pytest.raises(ValueError, match="Unknown rule"):
        parse_rules(text)


# A stray comma is a mistake of its own, not an unknown rule, and `v1,` is not v1 with others.
@pytest.mark.parametrize("text", ["O1,,O2", "O1,", ",O1", "O1, ,O2", "v1,", ","])
def test_parse_rules_rejects_empty_items(text: str):
    with pytest.raises(ValueError, match=r"^the list has an empty item; remove the extra comma$"):
        parse_rules(text)


def test_every_view_has_an_implemented_entry():
    assert set(rules.IMPLEMENTED) == set(get_args(View))


def test_rules_for_view_keeps_only_implemented_rules_in_order(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(rules.IMPLEMENTED, "pressure", frozenset({"O3", "O1", "O2"}))
    monkeypatch.setitem(rules.IMPLEMENTED, "perps", frozenset())

    assert rules_for_view("pressure", ALL_RULES) == ["O1", "O2", "O3"]
    assert rules_for_view("pressure", frozenset({"O3", "O6"})) == ["O3"]
    assert rules_for_view("pressure", frozenset()) == []
    # A rule that is on but not implemented for the view is not reported for it.
    assert rules_for_view("perps", ALL_RULES) == []


def test_settings_rules_default_to_all(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WHEELHOUSE_RULES", raising=False)
    assert Settings().rules == ALL_RULES
    assert Settings.from_env().rules == ALL_RULES
    monkeypatch.setenv("WHEELHOUSE_RULES", "")
    assert Settings.from_env().rules == ALL_RULES


def test_settings_rules_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WHEELHOUSE_RULES", "o2, O4")
    assert Settings.from_env().rules == {"O2", "O4"}
    monkeypatch.setenv("WHEELHOUSE_RULES", "v1")
    assert Settings.from_env().rules == frozenset()


@pytest.mark.parametrize("text", ["v1,O1", "O9", "O1,"])
def test_settings_rules_reject_bad_values(monkeypatch: pytest.MonkeyPatch, text: str):
    monkeypatch.setenv("WHEELHOUSE_RULES", text)
    with pytest.raises(ValueError, match="WHEELHOUSE_RULES"):
        Settings.from_env()
