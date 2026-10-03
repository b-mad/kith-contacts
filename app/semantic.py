"""Search by meaning (S-08, ADR-0013).

Contacts are turned into short text chunks, embedded with a local model and
stored in ``semantic_chunk``. A background task keeps them current; searches
compare the query's vector with every chunk in memory (exact, a few ms for
10,000 contacts) and report each contact's best chunk as the reason.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.embedder import Embedder, ModelUnavailable, Vectors, load_embedder
from app.models import Contact, ListMember, SemanticChunk, SemanticDoc
from app.search import SearchFilters, _with_details, query_terms

log = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 600
MAX_ACTIVITIES = 30
BATCH_CONTACTS = 32
RESULT_LIMIT = 8
# Tuned for all-MiniLM-L6-v2 (ADR-0013): cosine similarity of query and best chunk.
FLOOR = 0.40  # the query has no keyword match on all words: meaning leads
FLOOR_ALSO = 0.45  # keyword results exist: only clearly related extras
FLOOR_ONE_WORD = 0.45
WITHIN_BEST = 0.05

SOURCE_LABELS = {
    "profile": "profile",
    "works_on": "works on",
    "notes": "notes",
    "fields": "details",
    "activity": "activity",
}


# ---------------------------------------------------------------- chunks


@dataclass(frozen=True)
class Chunk:
    source: str
    text: str


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def split_text(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Paragraphs, then sentences, packed into pieces of at most ``limit`` characters."""
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n|\n", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        current = ""
        for sentence in _SENTENCE.split(paragraph):
            while len(sentence) > limit:  # a very long sentence: hard wrap
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(sentence[:limit])
                sentence = sentence[limit:]
            if current and len(current) + 1 + len(sentence) > limit:
                pieces.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            pieces.append(current)
    return pieces


def contact_chunks(contact: Contact) -> list[Chunk]:
    """The texts that describe a contact for search by meaning."""
    c = contact
    role = ", ".join(
        part
        for part in (
            c.title,
            f"{c.team} team" if c.team else None,
            c.department,
            f"at {c.company}" if c.company else None,
        )
        if part
    )
    profile = [c.display_name + (f" ({c.nickname})" if c.nickname else "") + "."]
    if role:
        profile.append(role.replace(", at ", " at ") + ".")
    profile.append(f"{c.contact_type.name}.")
    if c.location:
        profile.append(f"Based in {c.location}.")
    if c.manager is not None:
        profile.append(f"Reports to {c.manager.display_name}.")
    if c.tags:
        profile.append("Tags: " + ", ".join(t.name for t in c.tags) + ".")
    lists = [
        m.contact_list.name + (f" ({m.role_note})" if m.role_note else "")
        for m in sorted(c.memberships, key=lambda m: m.contact_list.name.lower())
    ]
    if lists:
        profile.append("Projects: " + ", ".join(lists) + ".")
    chunks = [Chunk("profile", piece) for piece in split_text(" ".join(profile))]
    if c.works_on:
        chunks += [Chunk("works_on", f"Works on {p}") for p in split_text(c.works_on)]
    if c.notes:
        chunks += [Chunk("notes", p) for p in split_text(c.notes)]
    if c.custom_fields:
        fields = "; ".join(f"{f.name}: {f.value}" for f in c.custom_fields)
        chunks += [Chunk("fields", p) for p in split_text(fields)]
    for a in c.activities[:MAX_ACTIVITIES]:  # newest first
        label = a.kind.capitalize()
        chunks += [
            Chunk("activity", f"{label} on {a.occurred_on.isoformat()}: {p}")
            for p in split_text(a.summary)
        ]
    return chunks


def chunks_hash(chunks: Sequence[Chunk], model_id: str) -> str:
    digest = hashlib.sha256(model_id.encode())
    for chunk in chunks:
        digest.update(b"\x00" + chunk.source.encode() + b"\x01" + chunk.text.encode())
    return digest.hexdigest()


# ---------------------------------------------------------------- indexing


def _load(session: Session, ids: Collection[int]) -> list[Contact]:
    return list(
        session.scalars(
            select(Contact)
            .where(Contact.id.in_(list(ids)))
            .options(
                selectinload(Contact.contact_type),
                selectinload(Contact.manager),
                selectinload(Contact.tags),
                selectinload(Contact.memberships).selectinload(ListMember.contact_list),
                selectinload(Contact.custom_fields),
                selectinload(Contact.activities),
            )
            .execution_options(populate_existing=True)
        ).all()
    )


def pending_ids(session: Session, model_id: str, limit: int = BATCH_CONTACTS) -> list[int]:
    """Contacts never indexed, marked stale, or indexed with another model."""
    stmt = (
        select(Contact.id)
        .outerjoin(SemanticDoc, SemanticDoc.contact_id == Contact.id)
        .where(
            or_(
                SemanticDoc.contact_id.is_(None),
                SemanticDoc.stale.is_(True),
                SemanticDoc.model != model_id,
            )
        )
        .order_by(Contact.id)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def index_contacts(session: Session, embedder: Embedder, ids: Collection[int]) -> int:
    """(Re)embed these contacts when their text changed; returns how many were embedded."""
    todo: list[tuple[Contact, list[Chunk], str]] = []
    for contact in _load(session, ids):
        chunks = contact_chunks(contact)
        digest = chunks_hash(chunks, embedder.model_id)
        doc = session.get(SemanticDoc, contact.id)
        if doc is not None and doc.doc_hash == digest and doc.model == embedder.model_id:
            doc.stale = False  # e.g. a change that does not affect the text
            continue
        todo.append((contact, chunks, digest))
    if not todo:
        session.flush()
        return 0
    vectors = embedder.embed([chunk.text for _, chunks, _ in todo for chunk in chunks])
    row = 0
    for contact, chunks, digest in todo:
        session.execute(delete(SemanticChunk).where(SemanticChunk.contact_id == contact.id))
        for chunk in chunks:
            session.add(
                SemanticChunk(
                    contact_id=contact.id,
                    source=chunk.source,
                    text=chunk.text,
                    vector=vectors[row].astype(np.float32).tobytes(),
                )
            )
            row += 1
        session.execute(
            insert(SemanticDoc)
            .values(
                contact_id=contact.id,
                model=embedder.model_id,
                doc_hash=digest,
                stale=False,
                embedded_at=func.clock_timestamp(),
            )
            .on_conflict_do_update(
                index_elements=[SemanticDoc.contact_id],
                set_={
                    "model": embedder.model_id,
                    "doc_hash": digest,
                    "stale": False,
                    "embedded_at": func.clock_timestamp(),
                },
            )
        )
    session.flush()
    return len(todo)


def index_pending(session: Session, embedder: Embedder, limit: int = BATCH_CONTACTS) -> int:
    ids = pending_ids(session, embedder.model_id, limit)
    return index_contacts(session, embedder, ids) if ids else 0


def index_all(
    session: Session, embedder: Embedder, *, progress: Callable[[int], None] | None = None
) -> int:
    """Index every pending contact (``make reindex``); commits per batch."""
    total = 0
    while ids := pending_ids(session, embedder.model_id):
        total += index_contacts(session, embedder, ids)
        session.commit()
        if progress:
            progress(total)
    return total


def mark_changed(session: Session, model_id: str, page: int = 500) -> int:
    """Hourly safety net: mark contacts stale whose text no longer matches their hash."""
    stored: dict[int, str] = {
        cid: digest
        for cid, digest in session.execute(
            select(SemanticDoc.contact_id, SemanticDoc.doc_hash).where(
                SemanticDoc.stale.is_(False), SemanticDoc.model == model_id
            )
        ).all()
    }
    ids = sorted(stored)
    changed: list[int] = []
    for start in range(0, len(ids), page):
        for contact in _load(session, ids[start : start + page]):
            if chunks_hash(contact_chunks(contact), model_id) != stored[contact.id]:
                changed.append(contact.id)
    if changed:
        session.execute(
            update(SemanticDoc).where(SemanticDoc.contact_id.in_(changed)).values(stale=True)
        )
    return len(changed)


def mark_all_stale(session: Session) -> None:
    session.execute(update(SemanticDoc).values(stale=True))


@dataclass(frozen=True)
class IndexCounts:
    contacts: int
    indexed: int
    pending: int


def index_counts(session: Session, model_id: str | None) -> IndexCounts:
    contacts = session.scalar(select(func.count()).select_from(Contact)) or 0
    current = (
        session.scalar(
            select(func.count())
            .select_from(SemanticDoc)
            .where(SemanticDoc.model == model_id, SemanticDoc.stale.is_(False))
        )
        if model_id
        else 0
    ) or 0
    return IndexCounts(contacts=contacts, indexed=current, pending=max(contacts - current, 0))


# ---------------------------------------------------------------- in-memory vectors


@dataclass(frozen=True)
class ChunkMatch:
    contact_id: int
    score: float
    source: str
    text: str


@dataclass
class _Entry:
    embedded_at: datetime
    vectors: Vectors
    chunks: list[tuple[str, str]]


class VectorIndex:
    """All chunk vectors of one instance, kept in step with the database."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[int, _Entry] = {}
        self._matrix: Vectors | None = None
        self._owners: np.ndarray | None = None
        self._refs: list[tuple[int, int]] = []

    def __len__(self) -> int:
        return len(self._entries)

    def sync(self, session: Session, model_id: str) -> None:
        current: dict[int, datetime] = {
            cid: at
            for cid, at in session.execute(
                select(SemanticDoc.contact_id, SemanticDoc.embedded_at).where(
                    SemanticDoc.model == model_id
                )
            ).all()
        }
        with self._lock:
            changed = [cid for cid, at in current.items() if self._at(cid) != at]
            removed = [cid for cid in self._entries if cid not in current]
        if not changed and not removed:
            return
        loaded: dict[int, _Entry] = {}
        for start in range(0, len(changed), 1000):
            ids = changed[start : start + 1000]
            rows = session.execute(
                select(
                    SemanticChunk.contact_id,
                    SemanticChunk.source,
                    SemanticChunk.text,
                    SemanticChunk.vector,
                )
                .where(SemanticChunk.contact_id.in_(ids))
                .order_by(SemanticChunk.contact_id, SemanticChunk.id)
            ).all()
            grouped: dict[int, list[tuple[str, str, bytes]]] = {}
            for cid, source, text_, vector in rows:
                grouped.setdefault(cid, []).append((source, text_, vector))
            for cid in ids:
                items = grouped.get(cid, [])
                vectors = (
                    np.vstack([np.frombuffer(v, dtype=np.float32) for _, _, v in items])
                    if items
                    else np.zeros((0, 0), dtype=np.float32)
                )
                loaded[cid] = _Entry(current[cid], vectors, [(s, t) for s, t, _ in items])
        with self._lock:
            for cid in removed:
                self._entries.pop(cid, None)
            self._entries.update(loaded)
            self._matrix = None

    def _at(self, contact_id: int) -> datetime | None:
        entry = self._entries.get(contact_id)
        return entry.embedded_at if entry else None

    def _build(self) -> None:
        parts: list[Vectors] = []
        owners: list[int] = []
        refs: list[tuple[int, int]] = []
        for cid, entry in self._entries.items():
            if entry.vectors.size:
                parts.append(entry.vectors)
                owners.extend([cid] * len(entry.chunks))
                refs.extend((cid, i) for i in range(len(entry.chunks)))
        self._matrix = np.vstack(parts) if parts else np.zeros((0, 1), dtype=np.float32)
        self._owners = np.array(owners, dtype=np.int64)
        self._refs = refs

    def query(
        self, vector: Vectors, *, allowed: Collection[int] | None = None, top: int = 30
    ) -> list[ChunkMatch]:
        """Best chunk per contact, highest similarity first."""
        with self._lock:
            if self._matrix is None:
                self._build()
            matrix, refs, entries = self._matrix, self._refs, self._entries
        if matrix is None or not refs:
            return []
        scores = matrix @ vector.astype(np.float32)
        out: list[ChunkMatch] = []
        seen: set[int] = set()
        for i in np.argsort(-scores):
            cid, n = refs[int(i)]
            if cid in seen or (allowed is not None and cid not in allowed):
                continue
            seen.add(cid)
            source, text_ = entries[cid].chunks[n]
            out.append(ChunkMatch(cid, float(scores[i]), source, text_))
            if len(out) >= top:
                break
        return out


# ---------------------------------------------------------------- service


@dataclass
class SemanticService:
    """Per-app state: the model (once loaded), the vector cache and status for Settings."""

    settings: Settings
    embedder: Embedder | None = None
    index: VectorIndex = field(default_factory=VectorIndex)
    unavailable: str | None = None
    last_error: str | None = None
    last_indexed_at: datetime | None = None
    _embed_lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def enabled(self) -> bool:
        return self.embedder is not None or self.settings.semantic_search != "off"

    @property
    def ready(self) -> bool:
        return self.embedder is not None

    @property
    def model_id(self) -> str | None:
        return self.embedder.model_id if self.embedder else None

    def load(self) -> bool:
        """Load the model from disk (slow: call off the event loop)."""
        if self.embedder is not None:
            return True
        if self.settings.semantic_search == "off":
            self.unavailable = "Turned off for this instance (SEMANTIC_SEARCH=off)."
            return False
        try:
            self.embedder = load_embedder(self.settings.resolved_model_dir)
        except ModelUnavailable as exc:
            self.unavailable = str(exc)
            return False
        except Exception as exc:  # a corrupt model file must not stop the app
            log.exception("could not load the search-by-meaning model")
            self.unavailable = f"The model could not be loaded: {exc}"
            return False
        self.unavailable = None
        return True

    def embed_query(self, text: str) -> Vectors:
        if self.embedder is None:  # pragma: no cover - callers check ready
            raise ModelUnavailable(self.unavailable or "not loaded")
        with self._embed_lock:
            vector: Vectors = self.embedder.embed([text])[0]
        return vector

    def index_pending(self, session: Session) -> int:
        if self.embedder is None:
            return 0
        with self._embed_lock:
            done = index_pending(session, self.embedder)
        if done:
            self.last_indexed_at = datetime.now().astimezone()
        return done


@dataclass(frozen=True)
class MeaningHit:
    contact: Contact
    score: float
    source: str
    text: str

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)


def search_by_meaning(
    session: Session,
    service: SemanticService,
    q: str,
    filters: SearchFilters | None = None,
    *,
    exclude: Iterable[int] = (),
    keyword_hits: int = 0,
    limit: int = RESULT_LIMIT,
) -> list[MeaningHit]:
    """S-08: people whose text is closest in meaning to ``q`` (ADR-0013 thresholds)."""
    terms = query_terms(q)
    if not service.ready or not terms or service.model_id is None:
        return []
    if len(terms) == 1 and keyword_hits:
        return []  # one word that already matches: keywords are the better answer
    skip = set(exclude)
    floor = FLOOR_ONE_WORD if len(terms) == 1 else FLOOR_ALSO if skip else FLOOR
    vector = service.embed_query(" ".join(q.split())[:500])
    service.index.sync(session, service.model_id)
    filters = filters or SearchFilters()
    allowed = set(session.scalars(filters.apply(select(Contact)).with_only_columns(Contact.id)))
    allowed -= skip  # people already listed by keyword search
    matches = service.index.query(vector, allowed=allowed)
    if not matches or matches[0].score < floor:
        return []
    cutoff = max(floor, matches[0].score - WITHIN_BEST)
    chosen = [m for m in matches if m.score >= cutoff][:limit]
    if not chosen:
        return []
    contacts = {
        c.id: c
        for c in session.scalars(
            _with_details(select(Contact)).where(Contact.id.in_([m.contact_id for m in chosen]))
        )
    }
    return [
        MeaningHit(contacts[m.contact_id], m.score, m.source, m.text)
        for m in chosen
        if m.contact_id in contacts
    ]
