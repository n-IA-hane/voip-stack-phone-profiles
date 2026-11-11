# SPDX-License-Identifier: MIT
import pytest
from jinja2 import Environment, StrictUndefined, UndefinedError

from phone_profiles.smarty import UnsupportedSmarty, compile_template


def evaluate(source, context=None):
    env = Environment(undefined=StrictUndefined, extensions=["jinja2.ext.loopcontrols"])
    return env.from_string(compile_template(source)).render(context or {})


@pytest.mark.parametrize("value", [None, False, 0, 0.0, "0", "", [], {}])
def test_php_false_values_are_not_jinja_string_truth(value):
    assert evaluate("{if $x}yes{else}no{/if}", {"x": value}) == "no"


def test_unset_and_nested_isset_short_circuit_with_strict_undefined():
    source = "{if isset($a.b.c)}set{else}absent{/if}"
    assert evaluate(source) == "absent"
    assert evaluate(source, {"a": {"b": {"c": None}}}) == "absent"
    assert evaluate(source, {"a": {"b": {"c": "0"}}}) == "set"
    with pytest.raises(UndefinedError):
        evaluate("{$required}")


@pytest.mark.parametrize("value", [0, "0", False])
def test_default_does_not_replace_zero_or_false(value):
    result = evaluate("{$x|default:'fallback'}", {"x": value})
    assert result != "fallback"


def test_default_replaces_only_unset_null_empty_string():
    for context in ({}, {"x": None}, {"x": ""}):
        assert evaluate("{$x|default:'fallback'}", context) == "fallback"


def test_array_assign_loop_and_replace():
    source = """{assign var=types value=['none'=>-1,'blf'=>1]}
{foreach $keys as $row}{$line=$row.id}{$types[$keys.$line.type]}:{$row.value|replace:' ':'_'};{/foreach}"""
    context = {"keys": {1: {"id": 1, "type": "blf", "value": "A B"}}}
    assert evaluate(source, context).strip() == "1:A_B;"


def test_loop_assignment_has_smarty_scope():
    source = (
        "{assign var=x value=1}{foreach $rows as $row}{$x}{assign var=x value=$x+1}{/foreach}:{$x}"
    )
    assert evaluate(source, {"rows": [1, 2, 3]}) == "123:4"


def test_literal_and_strip_are_preserved_semantically():
    assert (
        evaluate("{literal}{x+|[0-9]}{$not_a_variable}{/literal}") == "{x+|[0-9]}{$not_a_variable}"
    )
    assert evaluate("{strip}\n  a\n  b\n{/strip}") == "ab"
    assert evaluate("{strip}\n{$x}\n{/strip}", {"x": " a\n b "}) == " a\n b "


@pytest.mark.parametrize(
    "value,expected", [(None, ""), (False, ""), (True, "1"), (0, "0"), ("0", "0")]
)
def test_scalar_output_has_php_string_conversion(value, expected):
    assert evaluate("{$x}", {"x": value}) == expected


def test_for_and_break():
    assert evaluate("{for $i=1 to 5}{if $i == 3}{break}{/if}{$i}{/for}") == "12"


@pytest.mark.parametrize(
    "source",
    [
        "{include file='https://example.invalid/x'}",
        "{php}run{/php}",
        "{eval var=$x}",
        "{$x|not_implemented}",
        "{if filter_var($x,FILTER_VALIDATE_BOOLEAN)}x{/if}",
    ],
)
def test_unknown_or_executable_constructs_fail_closed(source):
    with pytest.raises(UnsupportedSmarty):
        compile_template(source)
