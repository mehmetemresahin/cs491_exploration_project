"""Entity resolution (MDM): link every extraction to a golden record in `entities`.

Precision first (report section 7: wrongly merging two companies is worse than missing a merge):
  1. A checksum-valid VKN is identity. Same VKN -> same entity; different VKNs never merge.
  2. Mentions without a valid VKN join the cluster whose names they match best, only if the
     match clears the threshold, beats the runner-up clearly, and the legal forms agree.
  3. Anything left over becomes its own entity rather than being guessed into one.
"""

import re
from collections import Counter
from dataclasses import dataclass

import duckdb
from rapidfuzz import fuzz
from rapidfuzz.distance import DamerauLevenshtein

from mock491 import vkn
from mock491.extract.common import fold

NAME_THRESHOLD = 88  # rapidfuzz ratio on core names, 0-100
WORD_THRESHOLD = 75  # every aligned word must be at least this similar (see name_similarity)
AMBIGUITY_MARGIN = 3  # best match must beat the next-best cluster by this much
NEAR_VKN_BONUS = 10  # an invalid VKN one digit away from the cluster's VKN is strong evidence

# Legal and trade boilerplate that says nothing about which company it is.
NOISE = {"san", "sanayi", "ve", "tic", "ticaret", "as", "anonim", "sirketi", "ltd", "limited",
         "sti"}  # fmt: skip
LEGAL_TOKENS = {"as": "AS", "anonim": "AS", "ltd": "LTD", "limited": "LTD"}


def parse_name(name: str) -> tuple[str, str | None]:
    """'DURDU ELEKTRİK SAN. VE TİC. A.Ş.' -> ('durdu elektrik', 'AS')"""
    s = fold(name)
    s = re.sub(r"\ba\.\s?s\.?", " as ", s)
    tokens = re.findall(r"[a-z0-9]+", s)
    legal = next((LEGAL_TOKENS[t] for t in tokens if t in LEGAL_TOKENS), None)
    return " ".join(t for t in tokens if t not in NOISE), legal


def name_similarity(a: str, b: str) -> float:
    """0-100. Whole-name ratio, vetoed if any word pair is clearly different.

    A whole-string ratio lets a long shared word ("yapi malzemeleri") outvote a different
    family name ("akca" vs "safak"), and scores "aslan" vs "eraslan" highly. Damerau-Levenshtein
    per word keeps a transposition typo ("drudu" vs "durdu") at one edit.
    """
    ta, tb = a.split(), b.split()
    if len(ta) == len(tb) and any(
        DamerauLevenshtein.normalized_similarity(x, y) * 100 < WORD_THRESHOLD
        for x, y in zip(ta, tb, strict=True)
    ):
        return 0.0
    return fuzz.ratio(a, b)


def one_digit_apart(a: str, b: str) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b, strict=True)) == 1


@dataclass
class Mention:
    extraction_id: str
    name: str
    raw_vkn: str | None
    core: str
    legal: str | None

    @property
    def valid_vkn(self) -> str | None:
        return self.raw_vkn if self.raw_vkn and vkn.is_valid(self.raw_vkn) else None


class Clusters:
    """Union-find over mentions; each cluster holds at most one valid VKN."""

    def __init__(self, mentions: list[Mention]):
        self.parent = {m.extraction_id: m.extraction_id for m in mentions}
        self.vkn = {m.extraction_id: m.valid_vkn for m in mentions}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        va, vb = self.vkn[ra], self.vkn[rb]
        if va and vb and va != vb:
            return False
        self.parent[rb] = ra
        self.vkn[ra] = va or vb
        return True


def _best_cluster(m: Mention, mentions: list[Mention], cl: Clusters) -> str | None:
    own = cl.find(m.extraction_id)
    best: dict[str, tuple[float, str]] = {}  # cluster root -> (score, matched core name)
    for other in mentions:
        root = cl.find(other.extraction_id)
        if root == own or (m.legal and other.legal and m.legal != other.legal):
            continue
        score = name_similarity(m.core, other.core)
        cluster_vkn = cl.vkn[root]
        if m.raw_vkn and cluster_vkn and one_digit_apart(m.raw_vkn, cluster_vkn):
            score += NEAR_VKN_BONUS
        if score > best.get(root, (-1, ""))[0]:
            best[root] = (score, other.core)

    # Prefer clusters anchored by a VKN; fall back to clusters of other VKN-less mentions.
    for anchored in (True, False):
        ranked = sorted(((s, core, r) for r, (s, core) in best.items()
                         if bool(cl.vkn[r]) == anchored), reverse=True)  # fmt: skip
        if not ranked or ranked[0][0] < NAME_THRESHOLD:
            continue
        top_score, top_core, top_root = ranked[0]
        for score, core, _ in ranked[1:]:
            if top_score - score >= AMBIGUITY_MARGIN:
                break
            # A close runner-up only matters if it looks like a different company;
            # another unmerged mention of the same company is not a rival.
            if name_similarity(core, top_core) < NAME_THRESHOLD:
                return None  # two plausible companies: leave it for a human rather than guess
        return top_root
    return None


def canonical_name(names: list[str]) -> str:
    """Display name: mixed case and Turkish letters first, then the most frequent spelling."""
    counts = Counter(names)
    return max(counts, key=lambda n: (not n.isupper(), not n.isascii(), counts[n]))


@dataclass
class ResolveStats:
    mentions: int
    entities: int
    by_vkn: int  # mentions linked through a valid VKN
    by_name: int  # mentions without a valid VKN that joined a cluster by name
    unresolved: int  # mentions without a valid VKN left in a cluster of their own


def resolve(con: duckdb.DuckDBPyConnection) -> ResolveStats:
    """Recompute all golden records from scratch (deterministic for the same extractions)."""
    rows = con.execute(
        "SELECT extraction_id, counterparty_name, counterparty_vkn FROM extractions "
        "ORDER BY extraction_id"
    ).fetchall()
    mentions = [Mention(eid, name, v, *parse_name(name)) for eid, name, v in rows]
    cl = Clusters(mentions)

    first_by_vkn: dict[str, str] = {}
    for m in mentions:
        if v := m.valid_vkn:
            cl.union(first_by_vkn.setdefault(v, m.extraction_id), m.extraction_id)

    by_name = 0
    for m in (m for m in mentions if not m.valid_vkn):
        target = _best_cluster(m, mentions, cl)
        if target and cl.union(target, m.extraction_id):
            by_name += 1

    groups: dict[str, list[Mention]] = {}
    for m in mentions:
        groups.setdefault(cl.find(m.extraction_id), []).append(m)
    entities = sorted(
        ((canonical_name([m.name for m in ms]), cl.vkn[root], ms) for root, ms in groups.items()),
        key=lambda e: (e[0], e[1] or ""),
    )

    con.execute("UPDATE extractions SET master_entity_id = NULL")
    con.execute("DELETE FROM entities")
    links = []
    for i, (name, entity_vkn, ms) in enumerate(entities, start=1):
        entity_id = f"GLD_ENT_{i:04d}"
        con.execute("INSERT INTO entities VALUES (?, ?, ?)", [entity_id, name, entity_vkn])
        links += [(m.extraction_id, entity_id) for m in ms]
    con.execute("CREATE OR REPLACE TEMP TABLE _links (extraction_id VARCHAR, entity_id VARCHAR)")
    con.executemany("INSERT INTO _links VALUES (?, ?)", links)
    con.execute(
        "UPDATE extractions SET master_entity_id = l.entity_id FROM _links l "
        "WHERE extractions.extraction_id = l.extraction_id"
    )

    no_vkn = [m for m in mentions if not m.valid_vkn]
    return ResolveStats(
        mentions=len(mentions),
        entities=len(entities),
        by_vkn=len(mentions) - len(no_vkn),
        by_name=by_name,
        unresolved=sum(1 for m in no_vkn if len(groups[cl.find(m.extraction_id)]) == 1),
    )
