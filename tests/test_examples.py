"""Smoke tests that guard the README/examples from bit-rotting."""

import runpy


def test_run_treasury_example_smoke(capsys):
    runpy.run_path("examples/run_treasury.py", run_name="__main__")
    out = capsys.readouterr().out
    assert "Overall (weighted)" in out
    assert "Gate:" in out


def test_run_email_example_smoke(capsys):
    runpy.run_path("examples/run_email.py", run_name="__main__")
    out = capsys.readouterr().out
    assert "Exfiltration demo:" in out
    assert "Gate:" in out
