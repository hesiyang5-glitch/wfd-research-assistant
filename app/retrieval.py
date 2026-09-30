"""Evidence retrieval over the case corpus: BM25 (keyword) + semantic ranking, fused by reciprocal rank.

Semantic ranking uses a configured embeddings endpoint (OpenAI-compatible, e.g. OpenAI or a local Ollama model)
when EMBEDDING_MODEL is set; otherwise it falls back to LSA (latent semantic analysis: TF-IDF + truncated SVD),
which captures word co-occurrence but is not a neural embedding. The active method is reported in the UI.
Queries are built from each variable's codebook definition, code labels and notes — never from incident-specific rules.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from . import db
from .config import env

STOP = set("""a an the and or of to in on for by with at from as is are was were be been being this that these those it its
into than then there their they them he she we you i not no but if so such can could would should may might must will shall do
does did has have had which who whom whose what when where why how all any each other some more most many much very also only
own same both few nor too s t just over under again further once here per via e g eg etc use used using whether indicates
indicator variable definition values value coded code codes field""".split())

# Domain vocabulary (codebook-level, applies to every case). Maps a term to extra search words.
EXPANSIONS = {
    "wea": "wireless emergency alert cell phone",
    "eas": "emergency alert system broadcast radio television",
    "nws": "national weather service noaa",
    "siren": "sirens outdoor warning",
    "latency": "delay minutes took later",
    "correction": "cancel cancellation retract retraction corrected clarification all clear follow-up",
    "cancellation": "cancel cancelled canceled rescinded",
    "coverage": "received percent reached residents subscribers signed up opt-in",
    "language": "spanish english bilingual translated translation",
    "protective": "evacuate shelter in place seek higher ground take cover",
    "approval": "approve authorization authorize permission clearance",
    "training": "trained untrained procedure protocol sop drill",
    "coordination": "coordinate coordinated between agencies county state",
    "platform": "everbridge codered alertsense genasys hyper-reach ipaws software vendor",
    "pathway": "text message phone broadcast social media website app",
    "outcomes": "deaths killed injured damage confusion panic",
    "harm": "deaths fatalities injuries killed damage dollars",
    "policy": "legislation bill law reform ordinance new procedure",
    "trust": "trust confidence credibility skepticism",
    "timeliness": "late too late minutes before after arrived",
    "media": "coverage outrage criticism headline",
    "population": "residents people households estimated",
    "demographic": "tourists elderly children students non-english low-income",
    "accessibility": "deaf blind disability captions language access",
    "reception": "confused confusion social media reaction",
    "archival": "screenshot text of the alert message read",
    "redundancy": "backup alternative multiple channels door-to-door",
    "summary": "alert warning failed failure",
}

_tok_re = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "edly", "ed", "ies", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in _tok_re.findall(text.lower()) if t not in STOP and len(t) > 1]


def variable_query(field: dict) -> str:
    name_words = " ".join(w for w in re.split(r"[_\W]+", field["name"].lower()) if w)
    parts = [name_words, name_words, field.get("definition", "")]
    parts += [c["label"] for c in field.get("codes", [])]
    parts += field.get("open_options", [])[:12]
    parts.append(field.get("notes", "")[:300])
    blob = " ".join(parts).lower()
    extra = [v for k, v in EXPANSIONS.items() if re.search(rf"\b{k}", blob)]
    return " ".join(parts + extra)


class CorpusIndex:
    def __init__(self, passages: list[dict]):
        self.passages = passages
        self.docs = [tokenize(p["text"]) for p in passages]
        self.N = len(self.docs)
        self.avgdl = (sum(len(d) for d in self.docs) / self.N) if self.N else 0
        self.df = Counter()
        for d in self.docs:
            self.df.update(set(d))
        self.tf = [Counter(d) for d in self.docs]
        self.semantic_method = "none"
        self._sem = None
        self._build_semantic()

    # -------------------------------------------------------------- BM25
    def bm25(self, query: str, k1=1.4, b=0.75) -> list[tuple[int, float]]:
        qt = tokenize(query)
        qc = Counter(qt)
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            dl = len(self.docs[i]) or 1
            for t, qn in qc.items():
                f = tf.get(t)
                if not f:
                    continue
                idf = math.log(1 + (self.N - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / (self.avgdl or 1))) * (1 + 0.2 * (qn - 1))
            if s > 0:
                scores.append((i, s))
        scores.sort(key=lambda x: -x[1])
        return scores

    # -------------------------------------------------------------- semantic
    def _build_semantic(self):
        if self.N < 2:
            return
        if env("EMBEDDING_MODEL"):
            try:
                from .llm.embeddings import embed_texts
                ids = [p["id"] for p in self.passages]
                vecs = embed_texts([p["text"] for p in self.passages], cache_ids=ids)
                import numpy as np
                m = np.array(vecs, dtype="float32")
                m /= (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
                self._sem = ("emb", m)
                self.semantic_method = f"embeddings ({env('EMBEDDING_MODEL')})"
                return
            except Exception as e:  # fall back but say so
                self.semantic_method = f"LSA fallback (embeddings failed: {str(e)[:80]})"
        try:
            import numpy as np
            from sklearn.decomposition import TruncatedSVD
            from sklearn.feature_extraction.text import TfidfVectorizer
            vec = TfidfVectorizer(tokenizer=tokenize, lowercase=False, token_pattern=None, sublinear_tf=True, min_df=1)
            X = vec.fit_transform([p["text"] for p in self.passages])
            k = max(2, min(120, X.shape[0] - 1, X.shape[1] - 1))
            svd = TruncatedSVD(n_components=k, random_state=0)
            Z = svd.fit_transform(X)
            Z /= (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)
            self._sem = ("lsa", Z, vec, svd)
            if self.semantic_method == "none":
                self.semantic_method = "LSA (latent semantic analysis; not a neural embedding)"
        except Exception as e:
            self.semantic_method = f"none (LSA unavailable: {str(e)[:60]})"

    def semantic(self, query: str) -> list[tuple[int, float]]:
        if not self._sem:
            return []
        import numpy as np
        if self._sem[0] == "emb":
            from .llm.embeddings import embed_texts
            qv = np.array(embed_texts([query])[0], dtype="float32")
            qv /= (np.linalg.norm(qv) + 1e-9)
            sims = self._sem[1] @ qv
        else:
            _, Z, vec, svd = self._sem
            qz = svd.transform(vec.transform([query]))[0]
            qz /= (np.linalg.norm(qz) + 1e-9)
            sims = Z @ qz
        order = np.argsort(-sims)
        return [(int(i), float(sims[i])) for i in order if sims[i] > 0.05]

    # -------------------------------------------------------------- hybrid
    def search(self, query: str, k: int = 8) -> list[dict]:
        lex = self.bm25(query)
        sem = self.semantic(query)
        fused: dict[int, float] = {}
        for r, (i, _) in enumerate(lex[:200]):
            fused[i] = fused.get(i, 0) + 1 / (60 + r)
        for r, (i, _) in enumerate(sem[:200]):
            fused[i] = fused.get(i, 0) + 1 / (60 + r)
        lex_s = dict(lex)
        sem_s = dict(sem)
        out = []
        for i, s in sorted(fused.items(), key=lambda x: -x[1])[:k]:
            out.append({**self.passages[i], "score": round(s, 5), "bm25": round(lex_s.get(i, 0), 3),
                        "semantic": round(sem_s.get(i, 0), 3)})
        return out


def load_case_passages(case_id: int, include_excluded: bool = False) -> list[dict]:
    sql = """SELECT p.id, p.source_id, p.seq, p.page, p.para, p.text, s.title, s.url, s.source_type
             FROM passages p JOIN sources s ON s.id=p.source_id
             WHERE p.case_id=? AND s.fetch_status='ok' AND s.duplicate_of IS NULL"""
    if not include_excluded:
        sql += " AND s.excluded=0 AND s.relevance_status!='irrelevant'"
    sql += " ORDER BY p.source_id, p.seq"
    return db.q(sql, (case_id,))


def evidence_strength(hits: list[dict], field: dict) -> float:
    """Rough 0..1 signal of whether the corpus seems to discuss this variable (used only to plan follow-up searches)."""
    if not hits:
        return 0.0
    best = max(h["bm25"] for h in hits)
    key = set(tokenize(" ".join(re.split(r"[_\W]+", field["name"].lower()))))
    covered = max(len(key & set(tokenize(h["text"]))) / (len(key) or 1) for h in hits)
    return round(min(1.0, best / 12.0) * 0.6 + covered * 0.4, 3)
