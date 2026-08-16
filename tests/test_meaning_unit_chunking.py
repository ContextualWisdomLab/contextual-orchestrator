"""Meaning-unit embeddings chunking: real invoice/email search accuracy.

Buyers embed AP mail and naruon DOM excerpts to retrieve *one* fact
(due date vs SKU vs sender). Token-midpoint splits mix those facts into one
vector. These tests use a real accounts-payable email and assert the splitter
keeps each meaning unit searchable on its own.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    TaskOrchestrator,
)
from contextual_orchestrator.batch_routing import (  # noqa: E402
    BatchJob,
    EmbeddingBatchRequest,
    EmbeddingBatchResultItem,
)
from contextual_orchestrator.meaning_unit_chunking import (  # noqa: E402
    MeaningUnitChunk,
    split_meaning_units,
)
from contextual_orchestrator.token_counting import HeuristicTokenCounter  # noqa: E402

# One-pixel PNG so the image unit is a real data URI, not a placeholder.
_PACKING_SLIP_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

ACCOUNTS_PAYABLE_EMAIL = (
    "From: billing@acme.example\n"
    "To: ap@buyer.example\n"
    "\n"
    "Invoice 1042 is due on 15 March 2026. Remit to Acme Treasury only.\n"
    "\n"
    "The packing list names SKU-77 and SKU-88. Do not pay SKU-99.\n"
    "\n"
    f"{_PACKING_SLIP_PNG}\n"
)


class _RecordingEmbeddingBackend:
    """Records mapped embedding parts so tests can inspect meaning units."""

    name = "recording"

    def __init__(self) -> None:
        self.requests: list[EmbeddingBatchRequest] = []

    def submit(self, requests, metadata=None):
        self.requests = list(requests)
        results = [
            EmbeddingBatchResultItem(
                custom_id=request.custom_id,
                index=position,
                embedding=[float(request.source_index), float(request.part_index)],
                prompt_tokens=request.token_count,
                model=request.model,
            )
            for position, request in enumerate(self.requests)
        ]
        self._results = results
        return BatchJob(
            job_id="meaning-unit-embeddings",
            backend=self.name,
            status="completed",
            request_count=len(self.requests),
        )

    def poll(self, job):
        return {"job_id": job.job_id, "status": "completed", "is_complete": True}

    def retrieve(self, job):
        return list(self._results)


def _count_tokens(text: str, model: str = "") -> int:
    return HeuristicTokenCounter(tokens_per_word=1.0).count_text(text, model)


def test_invoice_paragraphs_stay_separable_for_sku_search() -> None:
    """A due-date paragraph must not share a vector with the SKU packing list."""
    chunks = split_meaning_units(
        ACCOUNTS_PAYABLE_EMAIL,
        model="text-embedding-test",
        max_tokens=16,
        max_chars=240_000,
        count_tokens=_count_tokens,
    )
    texts = [chunk.chunk_text for chunk in chunks]
    due_date_chunks = [text for text in texts if "Invoice 1042" in text]
    sku_chunks = [text for text in texts if "SKU-77" in text]
    assert due_date_chunks, texts
    assert sku_chunks, texts
    assert all("SKU-77" not in text for text in due_date_chunks)
    assert all("Invoice 1042" not in text for text in sku_chunks)


def test_sender_block_is_its_own_meaning_unit() -> None:
    """From/To headers must be searchable without the invoice body."""
    chunks = split_meaning_units(
        ACCOUNTS_PAYABLE_EMAIL,
        model="text-embedding-test",
        max_tokens=16,
        max_chars=240_000,
        count_tokens=_count_tokens,
    )
    header_chunks = [chunk for chunk in chunks if chunk.unit_kind == "header_block"]
    assert header_chunks
    assert "billing@acme.example" in header_chunks[0].chunk_text
    assert "Invoice 1042" not in header_chunks[0].chunk_text


def test_embedded_image_keeps_source_offsets() -> None:
    """A data-URI image stays one unit and points at its original location."""
    chunks = split_meaning_units(
        ACCOUNTS_PAYABLE_EMAIL,
        model="text-embedding-test",
        max_tokens=16,
        max_chars=240_000,
        count_tokens=_count_tokens,
    )
    image_chunks = [chunk for chunk in chunks if chunk.unit_kind == "embedded_image"]
    assert len(image_chunks) == 1
    image = image_chunks[0]
    assert image.chunk_text.startswith("data:image/")
    restored = ACCOUNTS_PAYABLE_EMAIL[image.source_start : image.source_end]
    assert restored == image.chunk_text
    assert all(isinstance(chunk, MeaningUnitChunk) for chunk in chunks)
    assert all(chunk.source_start < chunk.source_end or chunk.chunk_text == "" for chunk in chunks)


def test_oversized_sentence_falls_back_without_mixing_neighbors() -> None:
    """A single oversized sentence may token-split; neighbors stay intact."""
    text = (
        "Pay SKU-77 now.\n\n"
        + ("word " * 40).strip()
        + ".\n\n"
        + "Invoice 1042 remains open."
    )
    chunks = split_meaning_units(
        text,
        model="text-embedding-test",
        max_tokens=8,
        max_chars=240_000,
        count_tokens=_count_tokens,
    )
    sku = next(chunk for chunk in chunks if "SKU-77" in chunk.chunk_text)
    invoice = next(chunk for chunk in chunks if "Invoice 1042" in chunk.chunk_text)
    assert "Invoice 1042" not in sku.chunk_text
    assert "SKU-77" not in invoice.chunk_text


def test_batch_embeddings_preserve_meaning_units_before_backend() -> None:
    """The batch path must forward meaning units, not word-packed mixes."""
    orchestrator = TaskOrchestrator(
        [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a", tags=("reasoning",))]
    )
    config = InMemoryConfigStore()
    config.set("routing", "embedding_max_tokens_per_request", 16)
    backend = _RecordingEmbeddingBackend()
    coordinator = CostRoutingCoordinator(
        orchestrator,
        config,
        token_counter=HeuristicTokenCounter(tokens_per_word=1.0),
        embedding_batch_backend=backend,
    )
    document = coordinator.complete_embeddings_batch(
        [ACCOUNTS_PAYABLE_EMAIL],
        model="text-embedding-test",
        attribution={"provider": "acme-provider"},
    )
    texts = [request.input_text for request in backend.requests]
    due_date = [text for text in texts if "Invoice 1042" in text]
    sku = [text for text in texts if "SKU-77" in text]
    assert due_date and sku
    assert all("SKU-77" not in text for text in due_date)
    assert all(getattr(request, "unit_kind", "") for request in backend.requests)
    assert document["input_part_counts"][0] == len(backend.requests)


def test_paper_docs_cite_passage_and_late_chunking() -> None:
    """Doctoring must name the retrieval papers that justify meaning units."""
    papers = (Path(__file__).resolve().parents[1] / "docs" / "papers" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "Karpukhin" in papers
    assert "2004.04906" in papers
    assert "Late chunking" in papers or "Late Chunking" in papers
    assert "2409.04701" in papers


if __name__ == "__main__":
    test_invoice_paragraphs_stay_separable_for_sku_search()
    test_sender_block_is_its_own_meaning_unit()
    test_embedded_image_keeps_source_offsets()
    test_oversized_sentence_falls_back_without_mixing_neighbors()
    test_batch_embeddings_preserve_meaning_units_before_backend()
    test_paper_docs_cite_passage_and_late_chunking()
    print("ok")
