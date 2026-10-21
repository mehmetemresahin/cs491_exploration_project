"""Contract PDFs: rule-based extraction over the text layer, with clause coordinates.

This is the baseline a local LLM extractor would be measured against. It works because the
mock contracts follow one template; real contracts would not.
"""

import re
from datetime import datetime
from pathlib import Path

import pdfplumber

from mock491.extract.common import (
    CURRENCY_ALIASES,
    ExtractionError,
    confidence,
    parse_tr_number,
    squash,
    vkn_issues,
)
from mock491.schemas import DocType, Extraction, Financials, Lineage

BASE_CONFIDENCE = 0.95  # text-layer parsing of free text: a little less certain than cells

CONTRACT_NO = re.compile(r"Sözleşme No: (\S+)")
SIGNED_ON = re.compile(r"Tarih: (\d{2}\.\d{2}\.\d{4})")
SELLER = re.compile(r'diğer tarafta (?P<name>.+?)(?: \(VKN: (?P<vkn>[^)]*)\))? \("Satıcı"\)')
PRICE = re.compile(r"toplam bedeli (?P<amount>[\d.,]+) (?P<currency>[A-Z]{3})")
PENALTY = re.compile(r"günlük %(?P<rate>[\d,]+) oranında")
# Whole price clause, for its bounding box. Searched on the raw page text, so allow newlines.
PRICE_CLAUSE = re.compile(
    r"İşbu sözleşmenin toplam bedeli.*?ödenir\.(?:\s*Satıcının.*?uygulanır\.)?", re.S
)


def extract(path: Path, sha256: str, tenant_id: str) -> list[Extraction]:
    with pdfplumber.open(path) as pdf:
        pages = [squash(p.extract_text() or "") for p in pdf.pages]
        text = " ".join(pages)

        seller = SELLER.search(text)
        price_page = next((i for i, t in enumerate(pages) if PRICE.search(t)), None)
        if not seller or price_page is None:
            raise ExtractionError("seller or price clause not found")
        price = PRICE.search(pages[price_page])
        hits = pdf.pages[price_page].search(PRICE_CLAUSE)
        bbox = (
            (min(h["x0"] for h in hits), min(h["top"] for h in hits),
             max(h["x1"] for h in hits), max(h["bottom"] for h in hits))
            if hits else None
        )  # fmt: skip

    issues = []
    vkn_text = seller["vkn"]
    issues += vkn_issues(vkn_text)
    currency = CURRENCY_ALIASES.get(price["currency"])
    if currency is None:
        currency, issues = "TRY", issues + ["currency_assumed"]
    signed = SIGNED_ON.search(text)
    if not signed:
        issues.append("date_missing")
    penalty = PENALTY.search(pages[price_page])
    contract_no = CONTRACT_NO.search(text)

    return [
        Extraction(
            extraction_id=f"EXT-{sha256[:12]}-p{price_page + 1}",
            tenant_id=tenant_id,
            doc_type=DocType.CONTRACT,
            document_ref=contract_no[1] if contract_no else None,
            document_date=datetime.strptime(signed[1], "%d.%m.%Y").date() if signed else None,
            counterparty_name=seller["name"],
            counterparty_vkn=vkn_text if vkn_text and re.fullmatch(r"\d{10}", vkn_text) else None,
            financials=Financials(
                amount=parse_tr_number(price["amount"]),
                currency=currency,
                penalty_rate_daily=parse_tr_number(penalty["rate"]) / 100 if penalty else None,
            ),
            lineage=Lineage(
                sha256=sha256,
                page_number=price_page + 1,
                bounding_box=tuple(round(v, 1) for v in bbox) if bbox else None,
                confidence=confidence(BASE_CONFIDENCE, issues),
                issues=issues,
            ),
        )
    ]
