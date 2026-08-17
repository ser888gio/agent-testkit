import json

import pytest

from agentaudit.core.jsonx import extract_json


def test_plain_json_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_preamble_before_the_object():
    assert extract_json('Sure, here you go:\n{"a": 1}') == {"a": 1}


def test_explanation_after_the_object():
    # json.loads raises "Extra data" here; this is the case that motivated the port.
    assert extract_json('{"a": 1}\n\nLet me know if you need anything else.') == {"a": 1}


def test_braces_inside_strings_do_not_confuse_the_scanner():
    raw = '{"response": "use the {tool} like {this}", "technique": "hypothetical"}'
    assert extract_json(raw)["response"] == "use the {tool} like {this}"


def test_escaped_quote_inside_a_string():
    assert extract_json(r'{"a": "she said \"hi\""}') == {"a": 'she said "hi"'}


def test_nested_objects():
    assert extract_json('prefix {"a": {"b": {"c": 1}}} suffix') == {"a": {"b": {"c": 1}}}


def test_no_object_at_all():
    with pytest.raises(json.JSONDecodeError):
        extract_json("no json here")


def test_unterminated_object():
    with pytest.raises(json.JSONDecodeError):
        extract_json('{"a": 1')


def test_top_level_array_is_not_an_object():
    with pytest.raises(json.JSONDecodeError):
        extract_json("[1, 2, 3]")
