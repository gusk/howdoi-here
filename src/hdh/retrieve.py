"""Query expansion and reranking.

The whole trick lives here: the user types "how do i map a list", and the fingerprint
turns that into a query that can only match *this* stack. Same words, different repo,
different results -- which is the property the test suite asserts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from hdh.fingerprint import Fingerprint
from hdh.index import Hit, Index

STOPWORDS = {
    "how", "do", "i", "you", "we", "to", "a", "an", "the", "in", "on", "of", "for", "with",
    "and", "or", "is", "are", "was", "be", "can", "could", "should", "would", "what", "whats",
    "why", "when", "where", "which", "who", "does", "did", "my", "our", "this", "that", "it",
    "its", "here", "there", "get", "make", "use", "using", "want", "need", "please", "help",
    "way", "best", "into", "from", "at", "by", "as", "if", "then", "so", "but", "not", "no",
}

# Question phrasing -> terms that actually appear in source. Cheap, high-yield synonym layer.
SYNONYMS = {
    "map": ["map", "comprehension", "transform", "select"],
    "list": ["list", "array", "slice", "vec", "collection"],
    "dict": ["dict", "map", "hashmap", "record", "object"],
    "loop": ["loop", "iterate", "range", "foreach", "each"],
    "test": ["test", "spec", "assert", "fixture", "mock"],
    "auth": ["auth", "authenticate", "token", "login", "credential", "session"],
    "log": ["log", "logger", "logging", "warn", "debug"],
    "error": ["error", "exception", "raise", "throw", "err", "panic"],
    "retry": ["retry", "backoff", "attempt", "resilient"],
    "config": ["config", "settings", "env", "options"],
    "http": ["http", "request", "client", "fetch", "get", "post"],
    "db": ["db", "database", "query", "session", "connection", "sql"],
    "async": ["async", "await", "concurrent", "goroutine", "future", "promise"],
    "parse": ["parse", "decode", "deserialize", "load"],
    "serialize": ["serialize", "encode", "dump", "marshal"],
    "cache": ["cache", "memo", "ttl", "invalidate"],
    "validate": ["validate", "schema", "check", "verify"],
    "sort": ["sort", "order", "sorted", "key"],
    "filter": ["filter", "where", "select", "reject"],
    "file": ["file", "path", "read", "write", "open"],
}

TEST_PATH_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)(test_|conftest)|(_test|\.test|\.spec)\.")
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")


@dataclass
class Retrieval:
    question: str
    keywords: list[str]
    context_terms: list[str]
    code: list[Hit] = field(default_factory=list)
    knowledge: list[Hit] = field(default_factory=list)
    match_expr: str = ""

    @property
    def empty(self) -> bool:
        return not self.code and not self.knowledge

    @property
    def all_hits(self) -> list[Hit]:
        return [*self.knowledge, *self.code]


def keywords(question: str) -> list[str]:
    words = [w.lower() for w in WORD_RE.findall(question)]
    kept = [w for w in words if w not in STOPWORDS and len(w) > 1]
    return list(dict.fromkeys(kept or words))


def expand(terms: list[str]) -> list[str]:
    out: list[str] = []
    for t in terms:
        out.append(t)
        out += SYNONYMS.get(t, [])
        if t.endswith("s") and len(t) > 3:
            out.append(t[:-1])
    return list(dict.fromkeys(out))


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def build_match(terms: list[str]) -> str:
    return " OR ".join(_quote(t) for t in terms if t)


def _rerank(hits: list[Hit], fp: Fingerprint, kws: set[str], wants_tests: bool) -> list[Hit]:
    primary = fp.primary
    scored: list[tuple[float, Hit]] = []
    for h in hits:
        score = -h.score  # bm25 is negative-better; flip so higher is better
        if primary and h.lang == primary:
            score *= 1.6
        elif h.lang in ("markdown", "text"):
            score *= 1.15
        if h.symbol and any(k in h.symbol.lower() for k in kws):
            score *= 1.4
        if TEST_PATH_RE.search(h.path):
            score *= 1.25 if wants_tests else 0.55
        if h.kind == "knowledge":
            score *= 1.3
        scored.append((score, h))
    scored.sort(key=lambda sh: -sh[0])
    return [h for _, h in scored]


def _dedupe(hits: list[Hit], per_file: int = 2) -> list[Hit]:
    seen: dict[str, int] = {}
    out: list[Hit] = []
    for h in hits:
        n = seen.get(h.path, 0)
        if n < per_file:
            seen[h.path] = n + 1
            out.append(h)
    return out


def retrieve(
    index: Index,
    fp: Fingerprint,
    question: str,
    max_code: int = 6,
    max_knowledge: int = 3,
) -> Retrieval:
    kws = keywords(question)
    ctx = fp.query_terms()
    expr = build_match(expand(kws))
    r = Retrieval(question=question, keywords=kws, context_terms=ctx, match_expr=expr)
    if not expr:
        return r

    kwset = set(kws)
    wants_tests = bool(kwset & {"test", "tests", "testing", "mock", "fixture", "spec"})
    pool = max(max_code, max_knowledge) * 6

    code = index.search(expr, limit=pool, kind="code")
    know = index.search(expr, limit=pool, kind="knowledge")

    # Fingerprint terms widen a thin result set, but never rescue an empty one: if the
    # user's own words match nothing, "python" matching everything is not an answer.
    if (code or know) and ctx and len(code) < max_code * 2:
        widened = build_match(ctx)
        r.match_expr = f"({expr}) + ({widened})"
        seen = {h.ref for h in code}
        code += [h for h in index.search(widened, limit=pool, kind="code") if h.ref not in seen]

    r.code = _dedupe(_rerank(code, fp, kwset, wants_tests))[:max_code]
    r.knowledge = _dedupe(_rerank(know, fp, kwset, wants_tests), per_file=1)[:max_knowledge]
    return r
