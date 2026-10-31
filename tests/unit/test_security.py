import pytest

from claimlens.adapters.local import LocalBlobStore
from claimlens.security import redact, safe_id


@pytest.mark.parametrize("bad", ["../etc", "a/b", "a b", "", "x" * 65, "a;b", "ａｂ", "t'1"])
def test_safe_id_rejects_path_and_injection_characters(bad: str) -> None:
    with pytest.raises(ValueError):
        safe_id(bad)


def test_safe_id_accepts_normal_ids() -> None:
    assert safe_id("clm_0123abcd-EF") == "clm_0123abcd-EF"


def test_blob_store_blocks_traversal(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = LocalBlobStore(tmp_path)
    store.put("raw/t1/c1/d1", b"x", "text/plain")
    assert store.get("raw/t1/c1/d1") == b"x"
    for bad in ["../outside", "raw/../../outside", "/abs/../../x", ""]:
        with pytest.raises(ValueError):
            store.put(bad, b"x", "text/plain")


def test_delete_prefix_removes_only_that_prefix(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = LocalBlobStore(tmp_path)
    store.put("raw/t1/c1/d1", b"a", "text/plain")
    store.put("raw/t1/c2/d1", b"b", "text/plain")
    assert store.delete_prefix("raw/t1/c1") == 1
    assert store.get("raw/t1/c2/d1") == b"b"
    with pytest.raises(FileNotFoundError):
        store.get("raw/t1/c1/d1")


def test_redaction() -> None:
    s = redact(
        "SSN 123-45-6789, mail a.b@example.com, phone (415) 555-0134, 415-555-0134, +1 415 555 0134 and 4155550134"
    )
    for token in ("123-45-6789", "a.b@example.com", "555-0134", "4155550134", "555 0134"):
        assert token not in s


def test_redaction_leaves_ordinary_numbers_alone() -> None:
    assert (
        redact("claim 12345 total $9,350.00 NPI 1003000126")
        == "claim 12345 total $9,350.00 NPI 1003000126"
    )
