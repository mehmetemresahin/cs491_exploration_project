"""Command line entry point: `python -m mock491 <command>`."""

import argparse
import shutil
import sys
from pathlib import Path

from mock491 import bronze, config, db, evaluate, extract, genbi, mockgen, resolve
from mock491.genbi import llm


def cmd_init(_: argparse.Namespace) -> None:
    with db.connect() as con:
        db.init_db(con)
    print(f"Warehouse ready at {config.WAREHOUSE_PATH}")


def cmd_generate(args: argparse.Namespace) -> None:
    truth = mockgen.generate(
        args.out,
        seed=args.seed,
        n_suppliers=args.suppliers,
        contracts_per_tenant=args.contracts,
        invoices_per_tenant=args.invoices,
    )
    print(
        f"{len(truth.tenants)} subsidiaries, {len(truth.entities)} suppliers, "
        f"{len(truth.records)} records -> {args.out}"
    )


def _files_under(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]


def cmd_ingest(args: argparse.Namespace) -> None:
    if args.by_folder:
        batches = [(d.name, _files_under(d)) for d in sorted(args.path.iterdir()) if d.is_dir()]
    elif args.tenant:
        batches = [(args.tenant, _files_under(args.path))]
    else:
        raise SystemExit("ingest needs --tenant or --by-folder")
    with db.connect() as con:
        db.init_db(con)
        for tenant, paths in batches:
            for p in paths:
                digest, new = bronze.ingest_file(con, p, tenant)
                print(f"{'+' if new else '='} {digest[:12]}  {tenant:<22} {p.name}")


def cmd_extract(args: argparse.Namespace) -> None:
    with db.connect() as con:
        db.init_db(con)
        stats = extract.run(con, redo=args.redo)
    print(f"{stats.files} files -> {stats.records} records, "
          f"{stats.pending_review} sent to human review")  # fmt: skip
    for name in stats.skipped:
        print(f"  skipped (no extractor): {name}")
    for name, err in stats.failed:
        print(f"  FAILED {name}: {err}")


def cmd_resolve(_: argparse.Namespace) -> None:
    with db.connect() as con:
        db.init_db(con)
        s = resolve.resolve(con)
    print(
        f"{s.mentions} mentions -> {s.entities} entities ({s.by_vkn} via VKN, "
        f"{s.by_name} via name, {s.unresolved} left on their own)"
    )


def cmd_evaluate(args: argparse.Namespace) -> None:
    truth = mockgen.load_truth(args.mock_dir)
    with db.connect(read_only=True) as con:
        print("== Extraction ==")
        print(evaluate.format_report(evaluate.evaluate(con, truth)))
        if con.execute("SELECT count(*) FROM entities").fetchone()[0]:
            print("\n== Entity resolution ==")
            print(evaluate.format_entity_report(evaluate.evaluate_entities(con, truth)))


def cmd_status(_: argparse.Namespace) -> None:
    if not config.WAREHOUSE_PATH.exists():
        print("No warehouse yet. Run `python -m mock491 init`.")
        return
    with db.connect(read_only=True) as con:
        for table, n in db.table_counts(con).items():
            print(f"{table:<20}{n:>6}")


def cmd_ask(args: argparse.Namespace) -> None:
    status = llm.configured()
    with db.connect(read_only=True) as con:
        if args.sql:
            answer = genbi.run_sql(con, args.sql, args.tenant)
        else:
            answer = genbi.ask(con, args.question, args.tenant, status.model)
    print(f"[{answer.source}] {answer.explanation}".rstrip())
    if answer.sql:
        print(f"\n{answer.sql}\n")
    if answer.error:
        print(f"Error: {answer.error}")
        if status.model is None and not args.sql:
            print(f"Model: {status.detail}")
    elif answer.rows is not None:
        print(answer.rows.to_string(index=False))
        if answer.truncated:
            print(f"(first {len(answer.rows)} rows)")


def cmd_reset(args: argparse.Namespace) -> None:
    if not args.yes:
        print(f"This deletes {config.DATA_DIR} except data/mock. Re-run with --yes.")
        return
    config.WAREHOUSE_PATH.unlink(missing_ok=True)
    # Bronze files are read-only by design, so clear the flag before deleting.
    if config.BRONZE_DIR.exists():
        shutil.rmtree(config.BRONZE_DIR, onexc=_force_remove)
    print("Warehouse and bronze cleared.")


def _force_remove(func, path, _exc) -> None:
    Path(path).chmod(0o666)
    func(path)


def main(argv: list[str] | None = None) -> None:
    # Windows consoles default to a legacy codepage that can't print every Turkish filename.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="mock491")
    sub = parser.add_subparsers(required=True)

    sub.add_parser("init", help="create warehouse tables and gold views").set_defaults(
        func=cmd_init
    )

    p = sub.add_parser("generate", help="write the synthetic holding dataset + ground truth")
    p.add_argument("--out", type=Path, default=config.MOCK_DIR)
    p.add_argument("--seed", type=int, default=491)
    p.add_argument("--suppliers", type=int, default=25)
    p.add_argument("--contracts", type=int, default=6, help="per subsidiary")
    p.add_argument("--invoices", type=int, default=30, help="per subsidiary")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("ingest", help="copy a file or folder into bronze")
    p.add_argument("path", type=Path)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--tenant", help="e.g. HOLDING_ENERJI_AS")
    group.add_argument(
        "--by-folder", action="store_true", help="each subfolder of PATH is one tenant"
    )
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("extract", help="parse bronze files into silver extractions")
    p.add_argument("--redo", action="store_true", help="re-extract everything (drops reviews)")
    p.set_defaults(func=cmd_extract)

    sub.add_parser("resolve", help="entity resolution: link extractions to golden records")\
        .set_defaults(func=cmd_resolve)  # fmt: skip

    p = sub.add_parser("evaluate", help="score extractions against the mock ground truth")
    p.add_argument("--mock-dir", type=Path, default=config.MOCK_DIR)
    p.set_defaults(func=cmd_evaluate)

    sub.add_parser("status", help="row counts per layer").set_defaults(func=cmd_status)

    p = sub.add_parser("ask", help="ask the gold layer a question (Text-to-SQL)")
    p.add_argument("question", nargs="?", default="")
    p.add_argument("--sql", help="run this SELECT instead of asking a model")
    p.add_argument("--tenant", help="answer as one subsidiary, e.g. HOLDING_ENERJI_AS")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("reset", help="delete warehouse and bronze files")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    args.func(args)
