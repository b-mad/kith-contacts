# ADR-0013: Search by meaning with a local model and in-process vectors (Phase 5)

- **Status:** Accepted (2026-10-03)
- **Date:** 2026-10-03
- **Deciders:** Bryan Madsen
- **Requirements affected:** S-08 (implementation); N-04 clarified; Phase 5 plan changed (pgvector → in-process vectors)

## Context

S-08 asks for natural-language search ("the person who helped with the FDA
submission") so people can be found when neither their name nor the exact words
are remembered. The Phase 5 plan assumed `pgvector` and a local embedding model.
Constraints: everything stays on the laptop (N-04), search stays under 200 ms
with 10,000 contacts (N-03), each instance is isolated (I-02), and the app must
keep working on a computer where the model is not installed.

## Options considered

1. **pgvector in PostgreSQL** — standard and indexable, but needs a different
   Docker image for every existing instance, an admin-only `CREATE EXTENSION`
   step per database (the app's role cannot create it), the same image in CI,
   and care in backup/restore. Its indexes only pay off well beyond 10,000 rows.
2. **Vectors in a plain table, compared in the app (chosen)** — vectors are
   stored as `bytea` in the instance's own database (so backups include them)
   and compared in memory with NumPy. With ≤ 10,000 contacts (~30,000 short
   text chunks × 384 numbers) an exact comparison takes a few milliseconds. No
   database change beyond two tables; easy to move to pgvector later.
3. **A hosted embedding API** — rejected: sends contact notes off the laptop (N-04).

For the model: `fastembed` and `sentence-transformers` were considered; both pull
in more than needed (`sentence-transformers` needs PyTorch). Running the ONNX
model directly with `onnxruntime` + `tokenizers` is ~60 lines and fully controlled.

## Decision

1. **Model.** `sentence-transformers/all-MiniLM-L6-v2` (Apache-2.0, 384
   dimensions, ~90 MB), ONNX export at a pinned revision, run with
   `onnxruntime` on the CPU (2 threads), mean pooling, L2-normalized vectors.
2. **Explicit, verified download.** `make model` downloads the two files from
   Hugging Face at the pinned revision into `~/.cache/contacts-app/models/`
   (shared by all instances) and checks each file's SHA-256 before keeping it.
   `make model FROM=<folder>` installs from a folder instead (for computers that
   can't reach Hugging Face). The app itself never downloads anything (N-04).
3. **Graceful absence.** If the model or `onnxruntime` is missing (no build
   exists for Intel Macs), the app runs normally without search by meaning and
   the Settings page says why. `SEMANTIC_SEARCH=off` turns it off per instance.
4. **What is indexed.** Each contact becomes short text chunks: a profile line
   (name, title, team, department, company, type, location, manager, tags, lists
   with roles), works-on, notes (split into paragraphs), extra fields, and the 30
   newest activity summaries. A contact's score is its best-matching chunk, and
   that chunk is shown as the reason for the match.
5. **Keeping it current.** Tables `semantic_doc` (one row per contact: model,
   hash of its chunks, stale flag, embedded time) and `semantic_chunk` (source,
   text, vector). `refresh_search` marks contacts stale; a background task in
   the running app embeds stale and new contacts in small batches every few
   seconds, and hourly re-checks every contact's hash to catch anything missed.
   Stale vectors keep answering until replaced. `make reindex I=<instance>`
   does the same without the app running.
6. **Presentation.** Keyword search (S-01–S-05) is unchanged. When keywords
   match every word, up to 8 more people appear after them as **"Also related,
   by meaning"** (similarity ≥ 0.45). When no one matches every word, the
   meaning matches come first as **"Best matches by meaning"** (≥ 0.40) and the
   partial keyword matches follow. Either way only results within 0.05 of the
   best one are shown, each with the text that matched, and nobody is listed
   twice. One-word queries use meaning only when keywords find no one (≥ 0.45).
   Filters apply to both. The thresholds are tuned for this model and checked
   by `make test-model`.
7. **Privacy.** Chunks and vectors are derived data: they are not exported, and
   an anonymized copy to dev (I-07) deletes them so they are rebuilt from the
   anonymized text.

## Consequences

- Each running instance with the model uses roughly 150 MB more memory, and
  embedding takes a few milliseconds per contact on Apple Silicon.
- Quality is good for descriptive questions about roles, projects and notes; it
  will not infer facts that were never written down ("the money person" will not
  find a CFO unless finance is mentioned).
- Changing the model later re-embeds everything automatically (the model name is
  stored per contact).
- Follow-up: pgvector if an instance ever grows far beyond 10,000 contacts.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| S-08 | Implemented as described above (Could, Phase 5). | — |
| N-04 | Clarified: the one-time, user-run model download (`make model`) is setup, not a runtime call. | — |
| Phase 5 | "Local semantic search with `pgvector`" → "with vectors stored in the instance database and compared in the app". | — |
