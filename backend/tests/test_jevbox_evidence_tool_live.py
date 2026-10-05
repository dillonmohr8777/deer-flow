"""Live, read-only Jevbox retrieval check. Opt-in only; $0 (no search/answer runs).

Requires DEER_FLOW_RUN_LIVE_TESTS=1, JEVBOX_EMAIL, JEVBOX_PASSWORD and
JEVBOX_LIVE_DOC_IDS (comma-separated, exactly 4 indexed document IDs). Load the
credentials from the protected store into the process environment at runtime;
never write them to disk.
"""

from __future__ import annotations

import os

import pytest

import deerflow.community.jevbox.tools as jevbox

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("DEER_FLOW_RUN_LIVE_TESTS") != "1" or not all(os.getenv(k) for k in ("JEVBOX_EMAIL", "JEVBOX_PASSWORD", "JEVBOX_LIVE_DOC_IDS")),
        reason="Requires DEER_FLOW_RUN_LIVE_TESTS=1 and Jevbox credentials/document IDs in the environment",
    ),
]

QUERY = os.getenv("JEVBOX_LIVE_QUERY", "review brief client route public observations draft context event")


def _settings(namespace: list[str]) -> jevbox.JevboxSettings:
    return jevbox.JevboxSettings(
        base_url=os.getenv("JEVBOX_BASE_URL", "http://localhost:4310"),
        email=os.environ["JEVBOX_EMAIL"],
        password=os.environ["JEVBOX_PASSWORD"],
        top_k=12,
        namespaces={"bar-crawl-usa": namespace},
    )


def test_live_scoped_retrieval_and_negative_exclusion():
    docs = [d.strip() for d in os.environ["JEVBOX_LIVE_DOC_IDS"].split(",") if d.strip()]
    assert len(docs) == 4
    excluded = docs[-1]

    full = jevbox.retrieve_evidence(_settings(docs), "bar-crawl-usa", QUERY)
    assert full.status == "ok", full.reason
    assert {p.document_id for p in full.passages} <= set(docs)
    assert len(full.review) == 4
    # Control: with the document authorized, the same query does return it.
    assert excluded in {p.document_id for p in full.passages}

    scoped = jevbox.retrieve_evidence(_settings(docs[:3]), "bar-crawl-usa", QUERY)
    assert scoped.status == "ok", scoped.reason
    assert scoped.passages
    assert excluded not in {p.document_id for p in scoped.passages}
    assert excluded not in jevbox.format_result(scoped, "bar-crawl-usa")

    denied = jevbox.retrieve_evidence(_settings(docs), "other-client", QUERY)
    assert denied.status == "denied" and not denied.passages

    print("\nLIVE full:", [(d, v, why) for d, v, why in full.review], [p.locator for p in full.passages])
    print("LIVE scoped:", [(d, v, why) for d, v, why in scoped.review], [p.locator for p in scoped.passages])
    print("LIVE other-client:", denied.status, denied.reason)
