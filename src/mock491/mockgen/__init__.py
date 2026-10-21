"""Synthetic holding dataset: documents per subsidiary plus the ground truth to score against.

Layout written to `out_dir`:
    <TENANT_ID>/sozlesmeler/<contract_no>.pdf
    <TENANT_ID>/faturalar_2026.xlsx
    ground_truth.json
"""

import random
import shutil
from datetime import date, timedelta
from pathlib import Path

from faker import Faker
from pydantic import BaseModel

from mock491.mockgen import render, world
from mock491.schemas import DocType

GROUND_TRUTH = "ground_truth.json"


class TruthEntity(BaseModel):
    entity_id: str
    canonical_name: str
    vkn: str
    sibling_of: str | None


class TruthRecord(BaseModel):
    record_id: str
    tenant_id: str
    doc_type: DocType
    file: str  # relative to the mock dir, posix
    page_number: int | None = None  # contracts
    bounding_box: tuple[float, float, float, float] | None = None  # contracts, pt, top-left
    row_number: int | None = None  # invoices, Excel row
    entity_id: str
    name_as_written: str
    name_variant: str
    vkn_as_written: str | None
    amount: float
    currency: str
    penalty_rate_daily: float | None = None
    paid: bool | None = None
    document_date: date


class GroundTruth(BaseModel):
    seed: int
    tenants: dict[str, str]
    entities: list[TruthEntity]
    records: list[TruthRecord]


def _contract_amount(rng: random.Random, currency: str) -> float:
    if currency == "TRY":
        return rng.randrange(500, 20_000) * 1_000.0
    return rng.randrange(20, 600) * 1_000.0


def generate(
    out_dir: Path,
    seed: int = 491,
    n_suppliers: int = 25,
    n_siblings: int = 3,
    contracts_per_tenant: int = 6,
    invoices_per_tenant: int = 30,
) -> GroundTruth:
    if out_dir.exists():
        if any(out_dir.iterdir()) and not (out_dir / GROUND_TRUTH).exists():
            raise FileExistsError(f"{out_dir} is not empty and is not a previous mock dataset")
        shutil.rmtree(out_dir)

    rng = random.Random(seed)
    fake = Faker("tr_TR")
    fake.seed_instance(seed)

    suppliers = world.build_suppliers(rng, fake, n_suppliers, n_siblings)
    # Zipf-like popularity (in shuffled order) so a few suppliers show up in every subsidiary.
    by_popularity = rng.sample(suppliers, len(suppliers))
    weights = [1 / (i + 1) ** 0.9 for i in range(len(suppliers))]
    # Every supplier, look-alikes included, gets at least one invoice in some random subsidiary.
    slots = [(t, i) for t in world.TENANTS for i in range(1, invoices_per_tenant + 1)]
    n_forced = min(len(slots), len(suppliers))
    forced = dict(zip(rng.sample(slots, n_forced), by_popularity[:n_forced], strict=True))
    records: list[TruthRecord] = []
    start = date(2026, 1, 1)

    for t_idx, (tenant_id, tenant_name) in enumerate(world.TENANTS.items()):
        for c in range(1, contracts_per_tenant + 1):
            sup = rng.choices(by_popularity, weights)[0]
            name, variant = world.write_name(sup, rng)
            vkn_text = world.write_vkn(sup, rng, p_missing=0.15)
            currency = rng.choices(["TRY", "USD", "EUR"], [5, 3, 2])[0]
            penalty = rng.choice([0.001, 0.0025, 0.005, 0.01]) if rng.random() < 0.8 else None
            filler = render.pick_filler(rng)
            spec = render.ContractSpec(
                contract_no=f"SOZ-{tenant_id.split('_')[1][:3]}-2026-{c:03d}",
                buyer_name=tenant_name,
                supplier_text=name,
                vkn_text=vkn_text,
                amount=_contract_amount(rng, currency),
                currency=currency,
                penalty_rate_daily=penalty,
                signed_on=start + timedelta(days=rng.randrange(270)),
                duration_months=rng.choice([6, 12, 24, 36]),
                filler=filler,
                price_after=rng.randint(len(filler) // 2, len(filler)),
            )
            rel = f"{tenant_id}/sozlesmeler/{spec.contract_no}.pdf"
            loc = render.render_contract(spec, out_dir / rel)
            records.append(
                TruthRecord(
                    record_id=spec.contract_no, tenant_id=tenant_id, doc_type=DocType.CONTRACT,
                    file=rel, page_number=loc.page_number,
                    bounding_box=tuple(round(v, 1) for v in loc.bounding_box),
                    entity_id=sup.entity_id, name_as_written=name, name_variant=variant,
                    vkn_as_written=vkn_text, amount=spec.amount, currency=currency,
                    penalty_rate_daily=penalty, document_date=spec.signed_on,
                )
            )  # fmt: skip

        rows: list[render.InvoiceRow] = []
        rel = f"{tenant_id}/faturalar_2026.xlsx"
        for i in range(1, invoices_per_tenant + 1):
            sup = forced.get((tenant_id, i)) or rng.choices(by_popularity, weights)[0]
            name, variant = world.write_name(sup, rng)
            currency = rng.choices(["TRY", "USD", "EUR"], [17, 2, 1])[0]
            amount = round(rng.uniform(10_000, 3_000_000 if currency == "TRY" else 90_000), 2)
            row = render.InvoiceRow(
                invoice_no=f"FTR{t_idx + 1}{i:05d}",
                issued_on=start + timedelta(days=rng.randrange(290)),
                supplier_text=name,
                vkn_text=world.write_vkn(sup, rng, p_missing=0.05),
                amount=amount,
                currency=currency,
                paid=rng.random() < 0.6,
            )
            rows.append(row)
            records.append(
                TruthRecord(
                    record_id=row.invoice_no, tenant_id=tenant_id, doc_type=DocType.INVOICE,
                    file=rel, row_number=i + 1, entity_id=sup.entity_id, name_as_written=name,
                    name_variant=variant, vkn_as_written=row.vkn_text, amount=amount,
                    currency=currency, paid=row.paid, document_date=row.issued_on,
                )
            )  # fmt: skip
        dialect = "A" if t_idx % 2 == 0 else "B"
        render.render_invoices(rows, dialect, out_dir / rel)

    truth = GroundTruth(
        seed=seed,
        tenants=world.TENANTS,
        entities=[
            TruthEntity(entity_id=s.entity_id, canonical_name=s.canonical_name, vkn=s.vkn,
                        sibling_of=s.sibling_of)
            for s in suppliers
        ],
        records=records,
    )  # fmt: skip
    (out_dir / GROUND_TRUTH).write_text(truth.model_dump_json(indent=2), encoding="utf-8")
    return truth


def load_truth(mock_dir: Path) -> GroundTruth:
    return GroundTruth.model_validate_json((mock_dir / GROUND_TRUTH).read_text(encoding="utf-8"))
