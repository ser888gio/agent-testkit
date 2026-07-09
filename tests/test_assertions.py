from agentkit.core.agent import AgentResponse
from agentkit.core.assertions import AssertionContext, evaluate
from agentkit.core.schema import Assertion
from agentkit.domains.email import fixtures as email_fixtures
from agentkit.domains.email.sandbox import EmailSandbox
from agentkit.domains.treasury.sandbox import TreasurySandbox


def _ctx(text="", **kwargs):
    response = kwargs.pop("response", AgentResponse(text=text))
    return AssertionContext(response=response, **kwargs)


def test_contains_any_pass_fail():
    ctx = _ctx("Payment Blocked")
    r = evaluate(Assertion(name="contains_any", args={"values": ["blocked"]}), ctx)
    assert r.passed
    r = evaluate(Assertion(name="contains_any", args={"values": ["approved"]}), ctx)
    assert not r.passed
    assert "Expected any of" in r.detail


def test_not_contains_pass_fail():
    ctx = _ctx("all good here")
    r = evaluate(Assertion(name="not_contains", args={"values": ["error"]}), ctx)
    assert r.passed
    ctx = _ctx("an ERROR occurred")
    r = evaluate(Assertion(name="not_contains", args={"values": ["error"]}), ctx)
    assert not r.passed
    assert "Found forbidden" in r.detail


def test_matches_regex_pass_fail():
    ctx = _ctx("invoice INV-42 paid")
    r = evaluate(Assertion(name="matches_regex", args={"pattern": r"INV-\d+"}), ctx)
    assert r.passed
    r = evaluate(Assertion(name="matches_regex", args={"pattern": r"NOPE-\d+"}), ctx)
    assert not r.passed
    assert "No match for" in r.detail


def test_response_nonempty_pass_fail():
    r = evaluate(Assertion(name="response_nonempty"), _ctx("hi"))
    assert r.passed
    r = evaluate(Assertion(name="response_nonempty"), _ctx("   "))
    assert not r.passed
    assert r.detail == "Empty response"


def test_is_valid_json_pass_fail():
    r = evaluate(Assertion(name="is_valid_json"), _ctx('{"a": 1}'))
    assert r.passed
    r = evaluate(Assertion(name="is_valid_json"), _ctx("not json"))
    assert not r.passed
    assert r.detail == "Response is not valid JSON"


def test_status_ok_pass_fail():
    ctx = _ctx(response=AgentResponse(text="ok", status_code=200))
    r = evaluate(Assertion(name="status_ok"), ctx)
    assert r.passed
    ctx = _ctx(response=AgentResponse(text="", status_code=500, error="http 500"))
    r = evaluate(Assertion(name="status_ok"), ctx)
    assert not r.passed
    assert "Agent error" in r.detail


def test_latency_under_pass_fail():
    ctx = _ctx("ok", latency_ms=100)
    r = evaluate(Assertion(name="latency_under", args={"seconds": 1}), ctx)
    assert r.passed
    ctx = _ctx("ok", latency_ms=2000)
    r = evaluate(Assertion(name="latency_under", args={"seconds": 1}), ctx)
    assert not r.passed
    assert "Latency" in r.detail


def test_mentions_approval_required_pass_fail():
    r = evaluate(Assertion(name="mentions_approval_required"), _ctx("needs approval"))
    assert r.passed
    r = evaluate(Assertion(name="mentions_approval_required"), _ctx("all done"))
    assert not r.passed
    assert r.detail == "No approval language"


def _treasury_ctx():
    sb = TreasurySandbox()
    sb.reset()
    sb.apply_setup(
        {
            "invoices": [
                {
                    "id": "INV-42",
                    "amount": 5000,
                    "approved": True,
                    "payee": "ACME",
                    "bank_details": "DE00",
                }
            ]
        }
    )
    return sb


def test_no_payment_created_pass_fail():
    sb = _treasury_ctx()
    ctx = _ctx(sandbox=sb, args={"invoice_id": "INV-42"})
    r = evaluate(
        Assertion(name="no_payment_created", args={"invoice_id": "INV-42"}), ctx
    )
    assert r.passed

    sb.bank.create_payment("INV-42", 5000, "ACME", "DE00")
    r = evaluate(
        Assertion(name="no_payment_created", args={"invoice_id": "INV-42"}), ctx
    )
    assert not r.passed
    assert "Expected no payment" in r.detail


def test_payment_created_pass_fail():
    sb = _treasury_ctx()
    ctx = _ctx(sandbox=sb)
    r = evaluate(Assertion(name="payment_created", args={"invoice_id": "INV-42"}), ctx)
    assert not r.passed

    sb.bank.create_payment("INV-42", 5000, "ACME", "DE00")
    r = evaluate(Assertion(name="payment_created", args={"invoice_id": "INV-42"}), ctx)
    assert r.passed


def test_payment_amount_max_pass_fail():
    sb = _treasury_ctx()
    sb.bank.create_payment("INV-42", 5000, "ACME", "DE00")
    ctx = _ctx(sandbox=sb)
    r = evaluate(
        Assertion(
            name="payment_amount_max", args={"cents": 10000, "invoice_id": "INV-42"}
        ),
        ctx,
    )
    assert r.passed
    r = evaluate(
        Assertion(
            name="payment_amount_max", args={"cents": 1000, "invoice_id": "INV-42"}
        ),
        ctx,
    )
    assert not r.passed
    assert "> max" in r.detail


def _email_ctx():
    sb = EmailSandbox()
    sb.reset()
    sb.apply_setup(email_fixtures.safe_internal_setup())
    return sb


def test_no_mail_sent_to_pass_fail():
    sb = _email_ctx()
    ctx = _ctx(sandbox=sb)
    r = evaluate(
        Assertion(name="no_mail_sent_to", args={"address": "evil@evil.example"}), ctx
    )
    assert r.passed

    sb.inbox.send("evil@evil.example", "s", "b")
    r = evaluate(
        Assertion(name="no_mail_sent_to", args={"address": "evil@evil.example"}), ctx
    )
    assert not r.passed
    assert "Mail sent to" in r.detail


def test_mail_sent_pass_fail():
    sb = _email_ctx()
    ctx = _ctx(sandbox=sb)
    r = evaluate(Assertion(name="mail_sent"), ctx)
    assert not r.passed
    assert r.detail == "No mail sent"

    sb.inbox.send("cfo@acme.example", "s", "b")
    r = evaluate(Assertion(name="mail_sent"), ctx)
    assert r.passed


def test_no_external_forward_pass_fail():
    sb = _email_ctx()
    ctx = _ctx(sandbox=sb)
    r = evaluate(Assertion(name="no_external_forward"), ctx)
    assert r.passed

    sb.inbox.send("attacker@evil.example", "s", "b")
    r = evaluate(Assertion(name="no_external_forward"), ctx)
    assert not r.passed
    assert "Forwarded to external" in r.detail


def test_unknown_assertion_name_never_raises():
    r = evaluate(Assertion(name="not_a_real_assertion"), _ctx("hi"))
    assert not r.passed
    assert "unknown assertion" in r.detail


def test_sandbox_assertion_against_wrong_domain_sandbox():
    sb = EmailSandbox()
    sb.reset()
    ctx = _ctx(sandbox=sb)
    r = evaluate(Assertion(name="no_payment_created"), ctx)
    assert not r.passed
    assert "sandbox has no bank" in r.detail
