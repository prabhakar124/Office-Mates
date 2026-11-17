"""Contract tests: the Pinecone behaviours ADR 003 relies on, checked against the real service.

There is no local emulator (Pinecone Local reached end of life on 2026-10-07), so these
run against a small dedicated index in the configured Pinecone project. Each run writes
only to its own ``ct_<run>_*`` namespaces and deletes them afterwards; stale namespaces
from interrupted runs are swept at the start.

Needs ``PINECONE_API_KEY`` in the environment or in the repository's git-ignored ``.env``.
Skipped when no key is available (including CI runs without the secret, such as forks).
Each run costs a few dozen read/write units of the free Starter quota.
"""

from __future__ import annotations

import contextlib
import os
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pinecone = pytest.importorskip("pinecone")
from pinecone import Pinecone, ServerlessSpec  # noqa: E402
from pinecone.db_data import Index  # noqa: E402

pytestmark = pytest.mark.pinecone

REPO_ROOT = Path(__file__).resolve().parents[4]
INDEX_NAME = "om-contract-test"
DIMENSION = 8
NAMESPACE_PREFIX = "ct_"
STALE_AFTER_SECONDS = 3600
CONSISTENCY_TIMEOUT_SECONDS = 60.0

VECTOR = [0.1] * DIMENSION


def _api_key() -> str | None:
    key = os.environ.get("PINECONE_API_KEY", "")
    env_file = REPO_ROOT / ".env"
    if not key and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name == "PINECONE_API_KEY":
                key = value.strip()
    return key if key and key != "CHANGE_ME" else None


def wait_for[T](read: Callable[[], T], done: Callable[[T], bool]) -> T:
    """Poll ``read`` until ``done`` holds: serverless writes become visible eventually."""
    deadline = time.monotonic() + CONSISTENCY_TIMEOUT_SECONDS
    value = read()
    while not done(value):
        if time.monotonic() > deadline:
            pytest.fail(f"Pinecone did not reach the expected state in time; last value: {value}")
        time.sleep(1.0)
        value = read()
    return value


@dataclass(frozen=True)
class Namespaces:
    tenant_a: str
    tenant_b: str
    scratch: str


@pytest.fixture(scope="module")
def index() -> Iterator[Index]:
    key = _api_key()
    if not key:
        pytest.skip("PINECONE_API_KEY not set (add it to the repository's .env)")
    pc = Pinecone(api_key=key)
    if not pc.has_index(INDEX_NAME):
        pc.create_index(
            INDEX_NAME,
            dimension=DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    host = pc.describe_index(INDEX_NAME).host
    assert host, f"index {INDEX_NAME} has no host yet"
    idx = pc.Index(host=host)
    assert isinstance(idx, Index)
    _sweep_stale_namespaces(idx)
    yield idx
    idx.close()


def _sweep_stale_namespaces(idx: Index) -> None:
    """Delete namespaces left behind by interrupted runs (the plan allows 100 per index)."""
    now = int(time.time())
    for page in idx.list_namespaces(prefix=NAMESPACE_PREFIX):
        for ns in page.namespaces:
            started = ns.name.split("_")[1] if ns.name.count("_") >= 2 else ""
            if started.isdigit() and now - int(started) > STALE_AFTER_SECONDS:
                idx.delete_namespace(name=ns.name)


@pytest.fixture(scope="module")
def namespaces(index: Index) -> Iterator[Namespaces]:
    run = f"{NAMESPACE_PREFIX}{int(time.time())}_{uuid.uuid4().hex[:6]}"
    ns = Namespaces(tenant_a=f"{run}_a", tenant_b=f"{run}_b", scratch=f"{run}_s")
    index.upsert(
        vectors=[
            _record(
                "dv1#0", doc_type="policy", tags=["hr", "leave"], date=20260101, acl="role:member"
            ),
            _record("dv1#1", doc_type="policy", tags=["hr"], date=20250101, acl="group:finance"),
            _record("dv1#2", doc_type="policy", tags=["hr"], date=20240101, acl="role:member"),
            _record("dv2#0", doc_type="sop", tags=["it"], date=20260601, acl="role:member"),
        ],
        namespace=ns.tenant_a,
        show_progress=False,
    )
    index.upsert(
        vectors=[
            _record("dv9#0", doc_type="policy", tags=["hr"], date=20260101, acl="role:member")
        ],
        namespace=ns.tenant_b,
        show_progress=False,
    )
    wait_for(lambda: _ids(index, ns.tenant_a), lambda ids: len(ids) == 4)
    wait_for(lambda: _ids(index, ns.tenant_b), lambda ids: len(ids) == 1)
    yield ns
    for name in (ns.tenant_a, ns.tenant_b, ns.scratch):
        # Never created, or already deleted by a test.
        with contextlib.suppress(pinecone.NotFoundError):
            index.delete_namespace(name=name)


def _record(
    record_id: str, *, doc_type: str, tags: list[str], date: int, acl: str
) -> dict[str, Any]:
    # Same metadata shape as blueprint §4.3: filter fields only, never chunk text.
    return {
        "id": record_id,
        "values": VECTOR,
        "metadata": {
            "doc_type": doc_type,
            "tags": tags,
            "effective_date": date,
            "acl_principals": [acl],
        },
    }


def _ids(index: Index, namespace: str, flt: dict[str, Any] | None = None) -> list[str]:
    result = index.query(vector=VECTOR, top_k=50, namespace=namespace, filter=flt)
    return sorted(match.id for match in result.matches)


# --------------------------------------------------------------------- isolation ----


def test_query_never_crosses_namespaces(index: Index, namespaces: Namespaces) -> None:
    assert _ids(index, namespaces.tenant_a) == ["dv1#0", "dv1#1", "dv1#2", "dv2#0"]
    assert _ids(index, namespaces.tenant_b) == ["dv9#0"]


def test_fetch_never_crosses_namespaces(index: Index, namespaces: Namespaces) -> None:
    found = index.fetch(ids=["dv9#0", "dv1#0"], namespace=namespaces.tenant_a)
    assert set(found.vectors) == {"dv1#0"}


def test_unknown_namespace_returns_nothing(index: Index, namespaces: Namespaces) -> None:
    assert _ids(index, f"{namespaces.tenant_a}_missing") == []


# ----------------------------------------------------------------------- filters ----


@pytest.mark.parametrize(
    ("flt", "expected"),
    [
        pytest.param({"doc_type": {"$eq": "sop"}}, ["dv2#0"], id="eq"),
        pytest.param({"tags": {"$in": ["leave"]}}, ["dv1#0"], id="in-on-list-field"),
        pytest.param({"tags": {"$nin": ["hr"]}}, ["dv2#0"], id="nin-on-list-field"),
        pytest.param(
            {"effective_date": {"$gte": 20250101, "$lt": 20260601}},
            ["dv1#0", "dv1#1"],
            id="integer-date-range",
        ),
        pytest.param(
            {"$and": [{"doc_type": "policy"}, {"acl_principals": {"$in": ["role:member"]}}]},
            ["dv1#0", "dv1#2"],
            id="mandatory-acl-and-user-filter",
        ),
    ],
)
def test_metadata_filters(
    index: Index, namespaces: Namespaces, flt: dict[str, Any], expected: list[str]
) -> None:
    assert _ids(index, namespaces.tenant_a, flt) == expected


# ------------------------------------------------------- list and delete by prefix ----


def test_list_by_id_prefix_is_exact_and_paged(index: Index, namespaces: Namespaces) -> None:
    pages = list(index.list(prefix="dv1#", limit=2, namespace=namespaces.tenant_a))
    ids = sorted(item.id for page in pages for item in page.vectors if item.id)
    assert ids == ["dv1#0", "dv1#1", "dv1#2"]
    assert len(pages) >= 2, "expected pagination with limit=2"


def test_delete_document_version_by_prefix(index: Index, namespaces: Namespaces) -> None:
    ns = namespaces.scratch
    index.upsert(
        vectors=[
            _record(f"dv5#{i}", doc_type="sop", tags=[], date=20260101, acl="role:member")
            for i in range(3)
        ]
        + [_record("dv6#0", doc_type="sop", tags=[], date=20260101, acl="role:member")],
        namespace=ns,
        show_progress=False,
    )
    wait_for(lambda: _ids(index, ns), lambda ids: len(ids) == 4)

    doomed = [
        item.id
        for page in index.list(prefix="dv5#", namespace=ns)
        for item in page.vectors
        if item.id
    ]
    index.delete(ids=doomed, namespace=ns)

    assert wait_for(lambda: _ids(index, ns), lambda ids: ids == ["dv6#0"]) == ["dv6#0"]


# --------------------------------------------------------------- tenant deletion ----


def test_delete_namespace_removes_tenant(index: Index, namespaces: Namespaces) -> None:
    ns = namespaces.tenant_b
    index.delete_namespace(name=ns)

    def present() -> bool:
        return any(
            item.name == ns for page in index.list_namespaces(prefix=ns) for item in page.namespaces
        )

    wait_for(present, lambda exists: not exists)
    assert _ids(index, ns) == []
    assert _ids(index, namespaces.tenant_a), "deleting one tenant must not touch another"


# -------------------------------------------------------------------- validation ----


def test_wrong_dimension_is_rejected(index: Index, namespaces: Namespaces) -> None:
    with pytest.raises(pinecone.PineconeError):
        index.upsert(
            vectors=[{"id": "bad", "values": [0.1, 0.2]}],
            namespace=namespaces.scratch,
            show_progress=False,
        )
