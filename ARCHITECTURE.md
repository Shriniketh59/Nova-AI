# Nova AI — Multimodal Agentic RAG Platform Architecture

Status: blueprint + skeleton. Real working code today: PDF/TXT/MD/CSV ingestion,
local Ollama embeddings+chat, Postgres-backed single-source RAG (`ragService.js`).
Everything else in this doc is a typed, runnable interface that throws
`not implemented` until built out — that's the intended shape of a 1-year
research project: stable contracts now, fill in the bodies over time.

## 1. System Overview

```
                         ┌─────────────────────┐
                         │      React UI        │
                         └──────────┬───────────┘
                                    │ REST + SSE
                         ┌──────────▼───────────┐
                         │   Express API layer   │  server/src/index.js, routes/
                         └──────────┬───────────┘
                                    │
                    ┌───────────────▼────────────────┐
                    │       SupervisorAgent            │  agents/supervisorAgent.js
                    │  (routes intent -> sub-agents)   │
                    └───┬───────┬───────┬───────┬─────┘
                        │       │       │       │
                ┌───────▼┐ ┌────▼───┐ ┌─▼──────┐ ┌▼────────┐
                │Planner │ │Knowledge│ │ Code   │ │Research │
                │Agent   │ │Agent    │ │ Agent  │ │Agent    │
                └────────┘ └────┬───┘ └────────┘ └────┬────┘
                                 │                      │
                         ┌───────▼──────────────────────▼───┐
                         │      RetrievalService              │  retrieval/
                         │ semantic + hybrid + rerank + compress│
                         └──────┬───────────────────┬─────────┘
                                │                    │
                        ┌───────▼──────┐    ┌────────▼────────┐
                        │   Qdrant      │    │   PostgreSQL    │
                        │ vectors+payload│    │ users/chats/meta│
                        └───────────────┘    └─────────────────┘
                                ▲
                    ┌───────────┴────────────┐
                    │   Knowledge Engine       │  knowledge/ingestors/
                    │ pdf/docx/pptx/csv/xlsx   │
                    │ code/repo/web/youtube/av │
                    └─────────────────────────┘
```

Every agent result passes through **ReviewAgent** before reaching the user
(confidence scoring, hallucination check against retrieved sources) — wired
as the last step in `supervisorAgent.js`.

## 2. Folder Structure

```
server/src/
  index.js                     # Express app, route registration
  db.js                        # Postgres pool + JSON fallback (existing)
  rag.js                       # low-level embed/chunk/parse/similarity (existing)

  knowledge/                   # Unified Knowledge Engine
    baseIngestor.js            # common interface: ingest(source) -> Chunk[]
    ingestorRegistry.js        # maps mime-type/source-type -> ingestor
    ingestors/
      pdfIngestor.js           # REAL (wraps existing parseDocument)
      textIngestor.js          # REAL (txt/md)
      csvIngestor.js           # REAL (row-wise chunks)
      excelIngestor.js         # stub (needs xlsx lib)
      docxIngestor.js          # stub (needs mammoth/docx lib)
      pptxIngestor.js          # stub (needs pptx-parser lib)
      codeIngestor.js          # stub (AST-aware chunking per language)
      repoIngestor.js          # stub (clone + walk + codeIngestor per file)
      webIngestor.js           # stub (fetch + readability extraction)
      youtubeIngestor.js       # stub (transcript fetch)
      audioIngestor.js         # stub (whisper.cpp / ollama audio model)
      videoIngestor.js         # stub (frame sample + audio track -> audioIngestor)

  retrieval/                   # Intelligent Retrieval
    qdrantClient.js            # thin REST wrapper around Qdrant
    retrievalService.js        # orchestrates the pipeline below
    semanticSearch.js          # REAL path, vector-only (current cosine impl generalized)
    hybridSearch.js            # stub: semantic + keyword (BM25-style) fusion
    queryExpansion.js          # stub: LLM-based query rewrite/expansion
    reranker.js                # stub: cross-encoder or LLM-based rerank
    contextCompression.js      # REAL (ported from ragService.js dedupe/compress)
    sourceAttribution.js       # REAL (extends sourceFormatter.js with page/line/confidence)

  agents/                      # Agentic Architecture
    baseAgent.js                # REAL (existing contract)
    supervisorAgent.js          # stub orchestrator: intent -> agent routing
    plannerAgent.js             # stub: task decomposition
    knowledgeAgent.js           # REAL thin wrapper over retrievalService + ragService
    codeAgent.js                # stub: multi-file gen, scaffolding, refactor
    researchAgent.js            # stub: multi-source synthesis
    reviewAgent.js              # stub: confidence scoring, hallucination check

  services/
    ragService.js                # REAL existing single-source RAG pipeline
    promptBuilder.js              # REAL existing
    sourceFormatter.js            # REAL existing

  jobs/                         # Performance: background processing
    indexingQueue.js             # stub: async background indexing job queue
    cache.js                     # stub: retrieval result cache (LRU/Redis-ready interface)

  routes/
    agentChat.js                 # SSE streaming endpoint -> SupervisorAgent

  utils/
    logger.js                    # REAL existing
```

## 3. Database Design

### PostgreSQL — system of record (users, chats, file tracking, metadata)

Extends existing schema (`migrations/001_initial_schema.sql`) with:

```sql
-- migrations/002_knowledge_metadata.sql

ALTER TABLE uploaded_files
  ADD COLUMN source_type   TEXT NOT NULL DEFAULT 'document', -- document|code|web|youtube|audio|video
  ADD COLUMN ingest_status TEXT NOT NULL DEFAULT 'pending',  -- pending|processing|indexed|failed
  ADD COLUMN qdrant_collection TEXT,
  ADD COLUMN source_url    TEXT;                              -- for web/youtube sources

-- document_chunks keeps existing pgvector-free JSON embedding column for the
-- current local fallback path; once Qdrant is live, this table stores ONLY
-- metadata (page/line/url) and the embedding moves to Qdrant payload+vector.
ALTER TABLE document_chunks
  ADD COLUMN page_number  INTEGER,
  ADD COLUMN line_start   INTEGER,
  ADD COLUMN line_end     INTEGER,
  ADD COLUMN qdrant_point_id UUID;

CREATE TABLE IF NOT EXISTS indexing_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  file_id UUID REFERENCES uploaded_files(id),
  status TEXT NOT NULL DEFAULT 'queued', -- queued|running|done|failed
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

### Qdrant — vector store (semantic retrieval)

One collection per source modality, so embedding dimension and payload shape
can differ per ingestor without cross-contaminating search:

```js
// qdrant/collections.js
{
  nova_documents:  { vectorSize: 384, distance: 'Cosine' }, // pdf/docx/pptx/csv/xlsx/txt/md
  nova_code:       { vectorSize: 384, distance: 'Cosine' }, // js/ts/py/java/cpp/repos
  nova_web:        { vectorSize: 384, distance: 'Cosine' }, // websites/docs/papers
  nova_media:      { vectorSize: 384, distance: 'Cosine' }  // youtube/audio/video transcripts
}
```

vectorSize 384 matches `all-minilm` (current local embed model). Swapping
embed models means recreating collections at that new size.

Payload schema (per point), used for metadata filtering + attribution:

```json
{
  "file_id": "uuid",
  "chat_id": "uuid",
  "filename": "AI_Notes.pdf",
  "source_type": "document",
  "page_number": 14,
  "line_start": null,
  "line_end": null,
  "content": "...chunk text...",
  "confidence_hint": 0.0
}
```

## 4. Retrieval Pipeline (target: <1s retrieval, <2s first token)

```
query
  -> queryExpansion()        // LLM rewrites query into 2-3 variants (parallel)
  -> semanticSearch() x N    // Qdrant search per variant, per relevant collection
  -> hybridSearch()          // fuse with keyword/BM25 results
  -> metadata filter         // chat_id / source_type / date scoping
  -> reranker()               // cross-encoder rescoring of top ~20 -> top K
  -> contextCompression()     // dedupe + budget-fit (existing logic, generalized)
  -> sourceAttribution()      // attach filename + page/line + confidence score
```

Speed levers (once Qdrant replaces local cosine-over-all-chunks):
- Qdrant HNSW index gives sub-100ms search vs current O(n) JS cosine loop.
- queryExpansion + multi-collection search run concurrently (`Promise.all`).
- reranker only runs on top-20 candidates, not the full retrieved set.
- Streaming starts as soon as the LLM emits its first token (existing SSE
  pattern in `index.js` query endpoint, reused for `routes/agentChat.js`).
- `jobs/indexingQueue.js` makes ingestion async — upload returns immediately,
  embedding/indexing happens in the background, chat polls/streams status.

## 5. Agent Responsibilities

| Agent | Responsibility | Status |
|---|---|---|
| SupervisorAgent | classify intent, route to one or more agents, merge results | stub |
| PlannerAgent | break multi-step asks into ordered sub-tasks | stub |
| KnowledgeAgent | run RetrievalService + ragService, return grounded answer | real wrapper |
| CodeAgent | multi-file generation, scaffolding, repo-aware refactor/debug | stub |
| ResearchAgent | synthesize across multiple retrieved sources into one narrative | stub |
| ReviewAgent | score confidence, flag unsupported claims, reject/repair | stub |

## 6. Source Grounding Format

Every agent response normalizes to:

```json
{
  "answer": "...",
  "sources": [
    { "index": 1, "filename": "AI_Notes.pdf", "page": 14, "confidence": 0.91 },
    { "index": 2, "filename": "ML_Book.pdf", "page": 220, "confidence": 0.84 },
    { "index": 3, "filename": "project.js", "lines": "50-80", "confidence": 0.77 }
  ]
}
```

`confidence` = normalized similarity score from retrieval, optionally
adjusted down by ReviewAgent if the answer drifts from cited content.

## 7. What's real vs. stub right now

Real: PDF/TXT/MD/CSV ingestion, Ollama embeddings (`all-minilm`) + chat
(`llama3.2:3b`), Postgres+JSON-fallback storage, single-collection cosine
retrieval, `ragService.js` grounded RAG, source citation by filename.

Stub (interface exists, throws `not implemented`): Qdrant client, DOCX/PPTX/
Excel/code/repo/web/YouTube/audio/video ingestors, hybrid search, query
expansion, reranking, all agents except KnowledgeAgent, background indexing
queue, caching.

Next concrete milestone (recommended): stand up Qdrant (Docker), migrate
existing PDF/TXT chunks into `nova_documents`, swap `ragService.js`'s
`searchRelevantChunks` for `retrievalService.semanticSearch` — that's the
one slice that turns the whole right column from stub to real fastest.
