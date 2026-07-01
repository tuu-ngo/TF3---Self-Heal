"""Test PII scrub — regex layer + key-name layer (bắt secret sai format)."""
from scrub import scrub_text, scrub_value, scrub_signal


def test_regex_layer_email_card_akid():
    assert "<EMAIL>" in scrub_text("contact bob@acme.com now")
    assert "<AWS_AKID>" in scrub_text("key AKIAIOSFODNN7EXAMPLE end")
    assert "<CARD>" in scrub_text("card 4111 1111 1111 1111 ok")


def test_key_name_layer_redacts_weird_format():
    # value không khớp bất kỳ regex nào nhưng key nhạy cảm -> vẫn redact
    assert scrub_value("db_password", "Xq9zNoRegex") == "<REDACTED>"
    assert scrub_value("authorization", "randomblob") == "<REDACTED>"
    assert scrub_value("aws-access-key-id", "plainish") == "<REDACTED>"
    # key thường -> giữ nguyên (không false-positive)
    assert scrub_value("service", "checkout") == "checkout"


def test_scrub_signal_labels_both_layers():
    sig = {"value": "user bob@acme.com", "labels": {
        "secret_token": "weirdFormat999", "service": "order-api"}}
    out = scrub_signal(sig)
    assert "<EMAIL>" in out["value"]
    assert out["labels"]["secret_token"] == "<REDACTED>"
    assert out["labels"]["service"] == "order-api"
    # không mutate gốc
    assert sig["labels"]["secret_token"] == "weirdFormat999"


def test_idempotent():
    once = scrub_text("bob@acme.com")
    assert scrub_text(once) == once
