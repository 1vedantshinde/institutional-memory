"""Tier-1 knowledge documents: extraction, chunking, glossary, ontology, retrieval, /chat."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

import core.config
from core.schema import Chunk, make_doc_id
from ingestion import knowledge_docs
from ingestion.chunker import default_semantic_split
from ingestion.parsers.pdf_parser import PDFParser
from llm.prompt_builder import build_document_answer_prompt, build_prompt, match_glossary

PDFS = knowledge_docs.KNOWLEDGE_DOCS_ROOT
EXPECTED_DOCS = sorted(knowledge_docs.CONCEPTS_PER_DOC.keys())



@pytest.fixture(scope="module")
def ingested():
    """Ingest the real PDFs once through the API's document pipeline (quietly)."""
    import api.main as daq_api

    with contextlib.redirect_stdout(io.StringIO()):
        result = knowledge_docs.ingest_knowledge_docs(daq_api.pipeline)
    return result


# --- Extraction --------------------------------------------------------------

@pytest.mark.parametrize("name,phrase", [
    ("glossary.pdf", "Mahalanobis distance"),
    ("machine_fact_sheet.pdf", "Latin square"),
    ("quarantine_policy_explainer.pdf", "canonical schema"),
    ("finding_explainer.pdf", "The AI explains, it doesn't invent"),
])
def test_pdfs_are_really_extracted_not_simulated(name: str, phrase: str) -> None:
    doc = PDFParser().parse(name, (PDFS / name).read_bytes())
    assert doc.metadata["parse_method"] == "pypdf"
    assert phrase.lower() in doc.raw_content.lower()


def test_a_real_pdf_without_text_is_never_decoded_as_bytes() -> None:
    doc = PDFParser().parse("broken.pdf", b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n")
    assert doc.raw_content == ""
    assert "%PDF" not in doc.raw_content


# --- Chunking ----------------------------------------------------------------

def test_chunks_start_and_end_on_word_boundaries() -> None:
    text = (PDFS / "glossary.pdf").read_bytes()
    doc = PDFParser().parse("glossary.pdf", text)
    chunks = default_semantic_split(doc)
    assert len(chunks) >= 2
    words = set(doc.raw_content.split())
    for chunk in chunks:
        assert chunk.text.split()[0] in words, f"chunk starts mid-word: {chunk.text[:20]!r}"
        assert chunk.text.split()[-1] in words, f"chunk ends mid-word: {chunk.text[-20:]!r}"


# --- Glossary ----------------------------------------------------------------

def test_domain_glossary_has_all_terms_from_the_pdf() -> None:
    domain = core.config.load_domain_config(str(Path(core.config.get_project_root()) / "config" / "domain.yaml"))
    terms = {item.term for item in domain.glossary}
    assert len(terms) == 18
    assert {"RMS", "Kurtosis", "Mahalanobis distance", "Latin-square design", "Raw voltage"} <= terms


@pytest.mark.parametrize("question,expected", [
    ("What does RMS mean?", {"RMS"}),
    ("Explain the Mahalanobis distance?", {"Mahalanobis distance"}),
    ("What's a latin square design?", {"Latin-square design"}),
    ("kurtosis vs crest-factor", {"Kurtosis", "Crest factor"}),
    ("How do the baselines work", {"Baseline"}),
    ("Tell me about the spindle", set()),
])
def test_glossary_matching_tolerates_punctuation_case_and_plurals(question, expected) -> None:
    assert {term for term, _ in match_glossary(question)} == expected


def test_glossary_accepts_meaning_or_definition_keys() -> None:
    domain = {"glossary": [{"term": "FCCU", "meaning": "Fluid Catalytic Cracking Unit"},
                           {"term": "SOP", "definition": "Standard Operating Procedure"}]}
    assert match_glossary("what is the fccu and an sop?", domain) == [
        ("FCCU", "Fluid Catalytic Cracking Unit"), ("SOP", "Standard Operating Procedure")]


def test_prompts_inject_only_terms_from_the_question() -> None:
    chunk = Chunk(chunk_id="c1", doc_id="d", text="The window, the baseline and the finding all use RMS.")
    prompt = build_prompt("What does kurtosis mean?", [chunk])
    assert "- Kurtosis:" in prompt
    assert "- Window:" not in prompt and "- RMS:" not in prompt  # mentioned only in context


def test_daq_prompt_does_not_define_condition_just_because_a_scope_is_named() -> None:
    from llm.prompt_builder import build_daq_explanation_prompt
    from core.schema import Finding

    finding = Finding(
        finding_id="f1", finding_type="anomaly", score=4.2, model_version="v", recording_id="4/Recording 1",
        evidence={"condition_id": "4", "channel": "Vib_Spindle", "window_id": "w", "source_path": "p",
                  "sample_range": {"sample_start": 0, "sample_end": 2048}},
    )
    prompt = build_daq_explanation_prompt("Is the RMS high for condition 4 spindle vibration?", [finding], {}, [])
    assert "- RMS:" in prompt
    assert "- Condition:" not in prompt


def test_document_prompt_is_evidence_only_and_labels_sources() -> None:
    chunk = Chunk(chunk_id="c1", doc_id="d", text="Quarantine keeps invented numbers out.", metadata={"source_path": "q.pdf"})
    prompt = build_document_answer_prompt("Why quarantine?", [chunk])
    assert "[Source 1] (from q.pdf)" in prompt
    assert "Do not calculate, estimate or invent" in prompt
    assert "- Quarantine:" in prompt


# --- Ingestion, ontology and retrieval ----------------------------------------

def test_all_documents_ingest_with_sane_chunk_counts(ingested) -> None:
    assert ingested["failed"] == {}
    assert sorted(ingested["documents"]) == EXPECTED_DOCS
    assert all(2 <= count <= 500 for count in ingested["documents"].values())


def test_documents_edges_link_each_pdf_to_its_concepts(ingested) -> None:
    from knowledge.graph_store import neo4j

    for name, concepts in knowledge_docs.CONCEPTS_PER_DOC.items():
        targets = {e.target for e in neo4j.get_neighbors(name) if e.type == "DOCUMENTS"}
        assert targets == set(concepts)
        assert neo4j.nodes[name]["label"] == "Document"
    assert knowledge_docs.documents_for_concepts("What's the difference between RMS and kurtosis?") == ["glossary.pdf"]


@pytest.mark.parametrize("question,expected_doc", [
    ("Why do some recordings get quarantined?", "quarantine_policy_explainer.pdf"),
    ("What is a Latin-square design and why does it matter here?", "machine_fact_sheet.pdf"),
    ("How is a Finding actually computed?", "finding_explainer.pdf"),
    ("What's the difference between RMS and kurtosis?", "glossary.pdf"),
    ("Condition 4 has an unusually high recording count — is that expected?", "machine_fact_sheet.pdf"),
])
def test_each_question_retrieves_the_right_document_first(ingested, question, expected_doc) -> None:
    from llm.orchestrator import retrieve_document_sources

    top = retrieve_document_sources(question)[0]
    assert top.doc_id == make_doc_id("text", expected_doc)


def test_keyword_search_ignores_punctuation(ingested) -> None:
    from retrieval.retriever import bm25_index

    hits = bm25_index.search("kurtosis?", top_k=5)
    assert hits and any(h.doc_id == make_doc_id("text", "glossary.pdf") for h in hits)



# --- /chat routing -----------------------------------------------------------

class _FakeLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        self.prompts.append(prompt)
        return "RMS is overall signal strength [Source 1]."


@pytest.fixture
def client(ingested, monkeypatch):
    from fastapi.testclient import TestClient
    import llm.orchestrator
    import server

    fake = _FakeLLM()
    monkeypatch.setattr(llm.orchestrator, "llm", fake)
    # No `with`: startup hooks (dataset warm start) don't run in tests
    return TestClient(server.app), fake


def test_chat_answers_a_general_question_from_the_knowledge_docs(client) -> None:
    http, fake = client
    res = http.post("/chat", json={"question": "What does RMS mean?"})
    assert res.status_code == 200
    body = res.json()
    assert body["route"] == "documents" and body["finding_count"] == 0 and body["citations"] == []
    assert body["sources"][0]["label"] == "Source 1"
    assert body["sources"][0]["source_path"] == "glossary.pdf"
    assert "- RMS: A single number that summarises how strong a signal is" in fake.prompts[0]


def test_chat_still_asks_for_scope_when_the_documents_have_nothing(client) -> None:
    http, fake = client
    res = http.post("/chat", json={"question": "zxqv plorb wuzzle?"})
    assert res.status_code == 422
    assert "condition" in res.json()["detail"]
    assert fake.prompts == []


def test_knowledge_docs_endpoint_lists_indexed_documents(client) -> None:
    http, _ = client
    body = http.get("/knowledge-docs").json()
    assert sorted(body["documents"]) == EXPECTED_DOCS
