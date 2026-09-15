"""Guards for customer-facing text: README, docstrings and examples must not
contradict the gateway on the points that were wrong once.

The gateway inserts the transaction row before the engine call and
uk_client_reference covers FAILED rows, so an engine-busy 503 consumes the
reference_id. Any sentence that promises "same reference_id" for a 503 without
that distinction is a regression.
"""

from __future__ import annotations

import re
from pathlib import Path

import paratro.transactions
from paratro import BadRequestError, ServiceUnavailableError, TransactionStatus, WebhookEventType

ROOT = Path(__file__).resolve().parent.parent
CUSTOMER_FACING = [ROOT / "README.md", ROOT / "CHANGELOG.md",
                   *sorted((ROOT / "paratro").glob("*.py")), *sorted((ROOT / "examples").glob("*.py"))]

# "same reference_id is fine" / "same ``reference_id`` may be retried" next to a 503 without qualification.
_STALE_503_CLAIMS = [
    re.compile(r"same\s+`{0,2}reference_id`{0,2}\s+(is fine|may be retried|can be retried)", re.I),
    re.compile(r"No transaction row was created", re.I),
    re.compile(r"没有建行"),
    # The post-insert failures do not always leave a FAILED row: a CONTRACT_CALL
    # refused after its permit was signed is held PENDING (gateway dispatchSettle
    # with livePermit → holdOperation), reservation locked until the permit
    # deadline. "row is now FAILED" / "row already FAILED" without that
    # qualification is the second thing that was wrong once.
    re.compile(r"\bnow FAILED\b"),
    re.compile(r"\brow (is|was|already) FAILED\b"),
    re.compile(r"row FAILED, retry"),
]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_file_claims_a_503_keeps_the_reference_id_unconditionally():
    offenders = []
    for path in CUSTOMER_FACING:
        for lineno, line in enumerate(_text(path).splitlines(), 1):
            if any(rx.search(line) for rx in _STALE_503_CLAIMS):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_readme_documents_both_503_variants_and_the_new_reference_rule():
    readme = _text(ROOT / "README.md")
    assert "Signing service is busy, retry later" in readme
    assert "Chain RPC unavailable; cannot verify request" in readme
    assert "is_engine_busy" in readme
    assert "Which errors consume `reference_id`" in readme
    # transaction_failed also lands after the insert.
    assert re.search(r"transaction_failed`? \(row FAILED", readme)


def test_readme_states_the_post_sign_rejected_exception_and_the_timeout():
    readme = _text(ROOT / "README.md")
    # CONTRACT_CALL: the post-sign re-verification rejects AFTER the row exists
    # (gateway contract_call.go VerifyExecuteSwap after signPermit).
    assert "post-sign" in readme
    assert "permit deadline" in readme
    # The replay of a 202 is HTTP 200 PENDING; ``accepted`` must not depend on the status alone.
    assert "`accepted` stays `True`" in readme or "accepted stays True" in readme
    # 200 s default, above the gateway's 180 s server write timeout (it answers
    # 202 at 150 s, so 150 s on the client would cut the 202 off).
    assert "timeout=200" in readme or "200 s" in readme
    assert "180 s" in readme
    # The 30 s value may only survive as the documented pre-1.8 behaviour.
    for lineno, line in enumerate(readme.splitlines(), 1):
        if "timeout=30" in line:
            assert "1.6" in line or "was" in line, f"README.md:{lineno}: {line.strip()}"
    assert "_HTTP_TIMEOUT = 200" in _text(ROOT / "paratro" / "client.py")
    # A stale 150 s default must not come back in the shipped docs.
    for path in (ROOT / "README.md", ROOT / "CHANGELOG.md"):
        text = _text(path)
        for stale in ("timeout=150", "**150 s**", "DEFAULT_TIMEOUT` (150", "DEFAULT_TIMEOUT` = 150", "default is now `150`"):
            assert stale not in text, f"{path.name} still documents a 150 s default: {stale}"


def test_readme_lists_every_webhook_event_and_status_constant():
    readme = _text(ROOT / "README.md")
    for value in (v for k, v in vars(WebhookEventType).items() if k.isupper()):
        assert f"`{value}`" in readme, value
    for value in (v for k, v in vars(TransactionStatus).items() if k.isupper() and isinstance(v, str)):
        assert f"`{value}`" in readme, value


def test_readme_403_row_mentions_address_blacklisted():
    readme = _text(ROOT / "README.md")
    assert "address_blacklisted" in readme


def test_transaction_status_in_flight_rule():
    for done in ("CANCELLED", "REJECTED", "COMPLIANCE_BLOCKED", "FAILED", "CONFIRMED",
                 "BROADCAST", "CONFIRMING", "SOMETHING_NEW"):   # unknown never spins a poll loop
        assert not TransactionStatus.is_in_flight(done), done
    for open_ in ("PENDING", "SIGNED", "PENDING_APPROVAL"):
        assert TransactionStatus.is_in_flight(open_), open_


def test_post_insert_failures_mention_the_held_pending_case_everywhere():
    """Engine-busy 503 and 400 transaction_failed: the row keeps the reference_id
    either as FAILED or — CONTRACT_CALL after a signed permit — held PENDING.
    Every customer-facing statement of those two cases must carry the second half.
    """
    readme = _text(ROOT / "README.md")
    table = readme[readme.index("### Which errors consume `reference_id`"):readme.index("### Idempotency-Key")]
    busy_row = next(l for l in table.splitlines() if l.startswith('| `503 "Signing service is busy'))
    failed_row = next(l for l in table.splitlines() if l.startswith("| `400 transaction_failed`"))
    for row in (busy_row, failed_row):
        assert "held" in row and "PENDING" in row and "**new** `reference_id`" in row, row
    # The 503 row of the error table and the except-branch comment say it too.
    err_503 = next(l for l in readme.splitlines() if l.startswith("| 503 | `ServiceUnavailableError`"))
    assert "held PENDING" in err_503 and "**new**" in err_503, err_503
    assert "row exists (FAILED, or held PENDING)" in readme

    def flat(doc):  # docstrings wrap; compare on collapsed whitespace
        return re.sub(r"\s+", " ", doc or "")

    for doc in (ServiceUnavailableError.__doc__, BadRequestError.__doc__, paratro.transactions.__doc__):
        assert "held PENDING" in flat(doc), doc
        assert "Duplicate reference_id" in flat(doc)
    assert "held PENDING" in flat(ServiceUnavailableError.is_engine_busy.__doc__)

    example = _text(ROOT / "examples" / "contract_call.py")
    assert "held PENDING" in example and "NEW reference_id" in example
