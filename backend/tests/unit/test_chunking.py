"""Tests for `app.storage.models.chunk_documents` (spec §44): Firestore's 500
writes/commit limit means we must chunk artifact writes at
`MAX_WRITES_PER_BATCH` (400), deterministically, preserving order.
"""

from __future__ import annotations

from app.storage.models import MAX_WRITES_PER_BATCH, chunk_documents


def test_empty_list_chunks_to_empty() -> None:
    assert chunk_documents([]) == []


def test_single_item_chunks_to_one_batch() -> None:
    result = chunk_documents([1])
    assert result == [[1]]


def test_exactly_max_size_is_one_batch() -> None:
    docs = list(range(MAX_WRITES_PER_BATCH))
    result = chunk_documents(docs)
    assert len(result) == 1
    assert result[0] == docs
    assert all(len(batch) <= MAX_WRITES_PER_BATCH for batch in result)


def test_one_over_max_size_spills_into_second_batch() -> None:
    docs = list(range(MAX_WRITES_PER_BATCH + 1))
    result = chunk_documents(docs)
    assert len(result) == 2
    assert [len(b) for b in result] == [MAX_WRITES_PER_BATCH, 1]
    assert all(len(batch) <= MAX_WRITES_PER_BATCH for batch in result)


def test_900_items_splits_into_three_batches_400_400_100() -> None:
    docs = list(range(900))
    result = chunk_documents(docs)
    assert [len(b) for b in result] == [400, 400, 100]
    assert all(len(batch) <= MAX_WRITES_PER_BATCH for batch in result)


def test_order_is_preserved_across_batches() -> None:
    docs = list(range(900))
    result = chunk_documents(docs)
    flattened = [item for batch in result for item in batch]
    assert flattened == docs
