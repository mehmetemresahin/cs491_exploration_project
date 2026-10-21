"""The fictional holding: subsidiaries, suppliers, and how supplier names get mangled."""

import random
from dataclasses import dataclass

from faker import Faker

from mock491 import vkn

TENANTS = {
    "HOLDING_ENERJI_AS": "Örnek Holding Enerji A.Ş.",
    "HOLDING_LOJISTIK_AS": "Örnek Holding Lojistik A.Ş.",
    "HOLDING_PERAKENDE_AS": "Örnek Holding Perakende A.Ş.",
    "HOLDING_INSAAT_AS": "Örnek Holding İnşaat A.Ş.",
}

SECTORS = [
    "Enerji", "Elektrik", "Lojistik", "Gıda", "Tekstil", "Makine", "Yapı Malzemeleri",
    "Yazılım", "Ambalaj", "Kimya", "Otomotiv", "Medikal", "Akaryakıt", "Güvenlik",
]  # fmt: skip

# legal form -> (long form, short form)
LEGAL_FORMS = {
    "AS": ("Sanayi ve Ticaret Anonim Şirketi", "San. ve Tic. A.Ş."),
    "LTD": ("Sanayi ve Ticaret Limited Şirketi", "San. ve Tic. Ltd. Şti."),
}

_ASCII = str.maketrans("şŞğĞıİçÇöÖüÜ", "sSgGiIcCoOuU")

# How a supplier's name is written in a given document, with relative frequency.
NAME_VARIANTS = {
    "canonical": 30,  # Durdu Elektrik San. ve Tic. A.Ş.
    "long": 15,  # Durdu Elektrik Sanayi ve Ticaret Anonim Şirketi
    "upper": 20,  # DURDU ELEKTRİK SAN. VE TİC. A.Ş.
    "ascii": 10,  # Durdu Elektrik San. ve Tic. A.S.
    "minimal": 15,  # Durdu Elektrik AŞ
    "typo": 10,  # Drudu Elektrik San. ve Tic. A.Ş.
}


@dataclass(frozen=True)
class Supplier:
    entity_id: str
    stem: str  # "Durdu Elektrik"
    legal: str  # key of LEGAL_FORMS
    vkn: str
    sibling_of: str | None = None  # set for look-alike companies that must NOT be merged

    @property
    def canonical_name(self) -> str:
        return f"{self.stem} {LEGAL_FORMS[self.legal][1]}"


def tr_upper(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def random_vkn(rng: random.Random) -> str:
    first = str(rng.randint(1, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(8))
    return first + str(vkn.check_digit(first))


def build_suppliers(rng: random.Random, fake: Faker, n: int, n_siblings: int) -> list[Supplier]:
    suppliers: list[Supplier] = []
    stems: set[str] = set()
    while len(suppliers) < n:
        stem = f"{fake.last_name()} {rng.choice(SECTORS)}"
        if stem in stems:
            continue
        stems.add(stem)
        suppliers.append(
            Supplier(f"ENT_{len(suppliers) + 1:04d}", stem, rng.choice(list(LEGAL_FORMS)),
                     random_vkn(rng))
        )  # fmt: skip

    # Look-alikes: same family name, different company. Hard negatives for entity resolution.
    for original in rng.sample(suppliers, n_siblings):
        family = original.stem.split()[0]
        sector = rng.choice([s for s in SECTORS if s not in original.stem])
        legal = "LTD" if original.legal == "AS" else "AS"
        suppliers.append(
            Supplier(f"ENT_{len(suppliers) + 1:04d}", f"{family} {sector}", legal,
                     random_vkn(rng), sibling_of=original.entity_id)
        )  # fmt: skip
    return suppliers


def write_name(supplier: Supplier, rng: random.Random) -> tuple[str, str]:
    """Return (name as it appears in a document, variant kind)."""
    kind = rng.choices(list(NAME_VARIANTS), weights=list(NAME_VARIANTS.values()))[0]
    long_form, short_form = LEGAL_FORMS[supplier.legal]
    canonical = supplier.canonical_name
    match kind:
        case "canonical":
            return canonical, kind
        case "long":
            return f"{supplier.stem} {long_form}", kind
        case "upper":
            return tr_upper(canonical), kind
        case "ascii":
            return canonical.translate(_ASCII), kind
        case "minimal":
            return f"{supplier.stem} {'AŞ' if supplier.legal == 'AS' else 'LTD'}", kind
        case "typo":
            # Swap two adjacent, different letters in the longest word (never the capital).
            words = supplier.stem.split()
            w = max(range(len(words)), key=lambda k: len(words[k]))
            word = words[w]
            spots = [i for i in range(1, len(word) - 1) if word[i] != word[i + 1]]
            if not spots:
                return canonical, "canonical"
            i = rng.choice(spots)
            words[w] = word[:i] + word[i + 1] + word[i] + word[i + 2 :]
            return f"{' '.join(words)} {short_form}", kind
    raise AssertionError(kind)


def write_vkn(supplier: Supplier, rng: random.Random, p_missing: float) -> str | None:
    """VKN as written: usually correct, sometimes absent, occasionally one digit off."""
    r = rng.random()
    if r < p_missing:
        return None
    if r < p_missing + 0.03:
        i = rng.randrange(10)
        wrong = str((int(supplier.vkn[i]) + rng.randint(1, 9)) % 10)
        return supplier.vkn[:i] + wrong + supplier.vkn[i + 1 :]
    return supplier.vkn
