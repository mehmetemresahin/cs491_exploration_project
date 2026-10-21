# CS491 Mock: Project Context

## What this repository is

An **early exploration mock** that comes before the real CS 491/492 project. The real project is
described in [`CS491_Keşif_Raporu.pdf`](CS491_Keşif_Raporu.pdf): an IDP + Data Lakehouse + GenBI
platform for multi-subsidiary holdings and banks.

The goal here is **not** to build that platform. The goal is to:

1. **Understand** the moving parts of the architecture by building a small version of each one.
2. Produce a **real but naive, visual demo** of the end result: scattered documents from different
   subsidiaries go in, and a consolidated, traceable risk view comes out.
3. Learn which parts are easy, which are hard, and what to ask stakeholders, before committing to
   the full stack.

Everything runs on **mock or synthetic data** (report section 8, risk 1). There are no real
company documents.

## Guiding principle: same shape, lighter tools

Every layer from the report exists here, so the mental model carries over. Each heavy component is
replaced by the lightest thing that still teaches the same lesson:

| Report layer | Report stack | Mock stand-in | Why |
|---|---|---|---|
| Orchestration & ingestion | Dagster / Airflow + Airbyte | `python -m mock491 ...` CLI | A few steps don't need a scheduler. Swap in Dagster once the pipeline has real stages. |
| Bronze (raw lake) | MinIO / S3 | `data/bronze/<tenant>/<sha256>.<ext>`, read-only files + manifest table | Keeps content addressing and immutability without running a server. |
| Silver / Gold storage | PostgreSQL + Iceberg | **DuckDB** single file (`data/warehouse.duckdb`) | Real SQL, zero setup, fast analytics. The SQL ports to Postgres almost unchanged. |
| Transformations | dbt | Plain SQL files (`src/mock491/sql/*.sql`): tables + `gold_*` views | Same idea as dbt models, without the dbt project overhead. |
| Parsing / OCR | Docling, PaddleOCR | `pdfplumber` text layer + word coordinates on generated (non-scanned) PDFs | We generate the PDFs ourselves, so we don't need OCR yet. Docling is the first upgrade. |
| LLM extraction | vLLM / Ollama + Instructor | Pydantic schemas (`schemas.py`) + rule-based extractor first, optional Ollama later | The **schema contract** is the important part. The model behind it is swappable. |
| Entity resolution | Splink | VKN identity + `rapidfuzz` name similarity with hand-set rules | Covers the report's Arçelik example. Splink (probabilistic, learns weights) pays off with more fields and more rows than we have. |
| Vector DB / RAG | Qdrant | Out of scope for now | Add it only if the demo needs "ask the PDF" questions. |
| BI & GenBI UI | Superset + LangGraph + Next.js | **Streamlit** multipage app (`app/`) over a UI-agnostic query layer (`queries.py`) | Python-only, fast to change. The query layer is what a later Next.js/FastAPI front end would reuse. |
| Text-to-SQL | LangGraph + local LLM | `genbi/`: one model call + one retry, local Ollama or the Anthropic API, SQL run in a locked sandbox | A single question→SQL→rows loop shows the idea and the safety model; an agent graph is not needed yet. |
| Human-in-the-loop | Custom review screen | `gold_review_queue` view + Review queue page: approve / reject / reopen (`review.py`) | The same 0.85 confidence threshold as the report. |

Concepts that are already in the foundation, because they shape the data model:

- **Lineage**: every extraction stores `sha256` (→ bronze file), `page_number`, `bounding_box` and
  `confidence`.
- **Multi-tenancy**: every row has a `tenant_id`. We filter in the app instead of using real RLS.
- **Golden record**: `entities.master_entity_id` links the same counterparty across subsidiaries.

## Layout

```
docs/                  report PDF + this file
src/mock491/
  config.py            paths, HITL threshold (MOCK491_DATA_DIR overrides data location)
  vkn.py               Turkish tax number checksum
  mockgen/             synthetic dataset: world.py (companies, name mangling), render.py (PDF/Excel)
  extract/             IDP stage: invoices.py, contracts.py, common.py (parsing + confidence policy)
  resolve.py           entity resolution: VKN identity + name matching -> golden records
  queries.py           read-side queries behind the UI (tenant-scopable); no Streamlit inside
  review.py            HITL decisions: approve / reject / reopen an extraction
  sources.py           open a bronze file at its lineage: rendered PDF page + highlight, sheet row
  evaluate.py          extraction field accuracy, bbox IoU, ER pairwise P/R/F1 vs ground truth
  schemas.py           Pydantic contracts: Extraction, Financials, Lineage
  bronze.py            content-addressed, immutable file ingest
  db.py                DuckDB connection, schema init, writes
  sql/silver.sql       bronze_files, extractions, entities, fx_rates (mock rates)
  sql/gold.sql         gold_extractions, gold_entity_exposure, gold_tenant_summary, gold_review_queue
  genbi/               Text-to-SQL: catalog.py (sandbox tables), guard.py (SQL checks), llm.py
                       (Ollama / Anthropic), examples.py (curated questions), __init__.py (ask)
  cli.py               init / generate / ingest / extract / resolve / evaluate / status / ask / reset
app/                   Streamlit UI, see [UI](#ui)
  main.py              entry point: navigation + sidebar
  views/               one file per page
  ui/                  theme, components, charts, cached data access, cross-page state
.streamlit/config.toml theme (light + dark), mirrors app/ui/theme.py
tests/                 pytest (71): foundation, mockgen, extract, resolve, review, genbi, ui smoke tests
data/                  generated, git-ignored
```

## Where we left off (2026-10-21)

**State:** all five roadmap steps are done and the full demo runs end to end: synthetic documents
→ bronze → extraction → entity resolution → gold views → a multipage Streamlit UI (overview,
counterparties with source drill-down, review queue, data & quality, ask the data). 71 tests pass,
ruff is clean. **No language model is connected yet**: Text-to-SQL answers the curated examples and
hand-written SQL until one is (see [Text-to-SQL](#text-to-sql)).

**To pick it up again:**

```powershell
.\.mock491_venv\Scripts\Activate.ps1
python -m mock491 reset --yes; python -m mock491 init; python -m mock491 generate
python -m mock491 ingest data/mock --by-folder; python -m mock491 extract; python -m mock491 resolve
python -m mock491 evaluate          # expect 100% extraction, 100% ER precision/recall
streamlit run app/main.py
```

**Open decisions and candidate next steps** (pick by what the team wants to learn):

1. **Connect a model and measure Text-to-SQL**: decide local Ollama (KVKK-friendly; this laptop has
   no NVIDIA GPU, so expect slow CPU answers) vs. the Anthropic API (fast, sends the question and
   table descriptions, not the data). Then score it on a question set with known answers.
2. **LLM extractor experiment**: an Ollama-backed extractor behind the same signature as the rule
   extractors, scored with `evaluate`. This shows what the report's "LLM + Pydantic" step really
   costs in accuracy and speed.
3. **Make the data harder**: scanned (image-only) PDFs that need OCR/Docling, layout changes, holding
   vs. subsidiary duplicates. Our current 100% scores mostly prove the plumbing, so a harder
   generator is what turns the evaluation into a real signal.
4. **Review with correction**: let a reviewer fix a value (e.g. the VKN), then re-run resolution.

**Questions for stakeholders that came out of the mock:** how often VKN/TCKN is really present per
source (it is the main lever for entity resolution), examples of real duplicate company pairs, and
which document types and layouts actually arrive.

## Roadmap (suggested order)

1. ~~**Mock data generator.**~~ Done. See [Mock dataset](#mock-dataset) below.
2. ~~**Extraction.**~~ Done (rule-based baseline). See [Extraction](#extraction) below. Next
   experiment: a local Ollama extractor behind the same `Extractor` signature, scored the same way.
3. ~~**Entity resolution.**~~ Done. See [Entity resolution](#entity-resolution) below.
4. ~~**Dashboard.**~~ Done, then rebuilt as a modular multipage app. See [UI](#ui) below.
5. ~~**Text-to-SQL.**~~ Done (model optional). See [Text-to-SQL](#text-to-sql) below.

## Mock dataset

`python -m mock491 generate` writes a fictional "Örnek Holding" to `data/mock/`. The output is
deterministic for a given `--seed`. With the defaults you get 4 subsidiaries, 25 suppliers plus 3
look-alike companies, and 144 records:

```
data/mock/
  HOLDING_ENERJI_AS/sozlesmeler/SOZ-ENE-2026-001.pdf ...   6 supply contracts (1-2 pages)
  HOLDING_ENERJI_AS/faturalar_2026.xlsx                    30 invoice rows
  ...one folder per subsidiary...
  ground_truth.json                                        the answer key
```

The dataset includes the mess we expect in real data, on purpose:

| Difficulty | How it appears | What it tests |
|---|---|---|
| Name variants | canonical / long legal form / UPPER (Turkish İ) / ASCII-folded / minimal "X AŞ" / letter-swap typo | entity resolution recall |
| Look-alike companies | Same family name, different sector and VKN (`sibling_of` in truth) | entity resolution **precision**: these must not merge |
| VKN noise | ~15% missing in contracts, ~5% in invoices, ~3% one digit off (fails checksum, see `vkn.py`) | how much we can rely on exact-key matching |
| Two spreadsheet layouts | Dialect A: typed date and amount columns. Dialect B: `"2.829.919,03 TL"` strings, `ÖDENDİ`, different headers | schema mapping and parsing Turkish number formats |
| Clause position | The price/penalty clause lands on page 1 or 2. Its page and bounding box (pt, top-left origin) are recorded | lineage / citation |
| Currencies | TRY / USD / EUR, so amounts must be normalized with `fx_rates` | gold-layer KPIs |
| Spread across subsidiaries | Zipf-like popularity: some suppliers show up in all 4 subsidiaries, and every supplier appears at least once | the consolidated exposure story |

Each `ground_truth.json` record points to its source (`file` + `page_number` or `row_number`) and
holds the true `entity_id`, the name and VKN *as written*, the amount, the currency and the penalty.
Extraction and entity resolution get scored against it.

Fonts: fpdf2's built-in fonts can't render Turkish characters. The generator looks for
`assets/fonts/DejaVuSans.ttf`, then system Arial or DejaVu, or uses the `MOCK491_FONT` env var.

## Extraction

`python -m mock491 extract` reads every bronze file that has no extractions yet. It writes
validated `Extraction` rows to `extractions`. `python -m mock491 evaluate` then scores them against
`ground_truth.json`.

- **Invoices** (`extract/invoices.py`): headers are mapped onto one schema through an alias table,
  compared case- and diacritic-insensitively, so `TEDARIKCI_UNVANI` matches "Tedarikçi Unvanı".
  Typed cells and `"2.829.919,03 TL"` strings both parse. An unknown layout fails loudly.
- **Contracts** (`extract/contracts.py`): pdfplumber's text layer plus regexes for seller, VKN,
  price, currency and penalty. The price clause's page and **bounding box** come from pdfplumber
  word coordinates, which gives real lineage for the "show me the source" view.
- **Confidence**: a base score per source type (cells 0.99, PDF text 0.95), minus a penalty per
  issue (`extract/common.py`: `vkn_missing` −0.15, `vkn_checksum` −0.30, …). Below 0.85 the row
  goes to `pending_review`, and its `issues` list tells the reviewer why.

**Current score: 100% on every field, and the review queue holds exactly the records whose VKN is
missing or invalid.** Read that with care: the rules were written against our own generator's
template, so the score proves the plumbing, not real-world accuracy. The harness is the lasting
value. Swap in an LLM extractor, or make the generator messier (scanned pages, layout changes), and
the same `evaluate` command shows what breaks.

## Entity resolution

`python -m mock491 resolve` rebuilds `entities` (golden records) from scratch and sets
`extractions.master_entity_id`. `evaluate` reports **pairwise precision / recall / F1** (report
section 7, row 3) and lists every wrong merge and split by name. The rules (`resolve.py`) are
precision first:

1. **A checksum-valid VKN is identity.** Same VKN means one entity. Two different valid VKNs never
   merge.
2. **Records without a valid VKN** are matched by name on a normalized *core*: Turkish-aware
   case/diacritic folding, with legal boilerplate (`San. ve Tic.`, `A.Ş.`, `Ltd. Şti.`) removed. A
   match needs core similarity ≥ 88, **and every aligned word** ≥ 75 (Damerau-Levenshtein, so a
   letter swap counts as one edit), **and** the same legal form (A.Ş. ≠ Ltd. Şti.). An invalid VKN
   one digit away from a cluster's VKN adds +10.
3. VKN-anchored clusters are tried first. If two *different-looking* companies match about equally
   well, the record stays on its own rather than being guessed into either.

**Results:** 100% precision and recall on the default dataset and on 5 larger seeds (40 suppliers,
50 invoices per subsidiary).

**What the experiments showed.** Hiding every VKN makes the matcher rely on names alone:

| Setup (names only) | Outcome on 5 seeds |
|---|---|
| Whole-string similarity, first version | Recall ~2%. Bug: identical VKN-less names blocked each other as "ambiguous". Fixed. |
| Whole-string similarity, bug fixed | ~99% F1 but **real wrong merges**: "Aslan Yazılım" + "Eraslan Yazılım", "Akça Yapı Malzemeleri" + "Şafak Yapı Malzemeleri" (the long shared sector word outvotes the family name) |
| + per-word check (current) | 100% on 4 seeds, 1 missed pair on the 5th, zero wrong merges |
| Current, but legal form ignored | Wrong merges return: "Tevetoğlu Kimya A.Ş." + "Tevetoğlu Kimya Ltd. Şti." |

Takeaways for the real project and the stakeholder questions:
- **VKN coverage is the main lever.** Ask how often VKN/TCKN is actually present in each source
  (report section 9, question 3). Names alone are workable but fragile.
- **Legal form is a cheap and strong signal.** Keep it as a hard rule.
- Our look-alikes are synthetic. Real hard cases (holding vs. its subsidiary, renamed companies,
  branches with shared VKN) are not modeled yet. That is a good reason to ask stakeholders for
  examples of real duplicate pairs.

## UI

`streamlit run app/main.py` (from the project root, so `.streamlit/config.toml` applies). Light and
dark mode both work. The sidebar's **Viewing as** box narrows every page to one subsidiary, as a
stand-in for row-level security.

| Page | Answers | Main interactions |
|---|---|---|
| **Overview** | How much do we owe whom, across all subsidiaries? | KPI row, top counterparties stacked by subsidiary, exposure per subsidiary, "Review now" callout, click a counterparty to open its profile |
| **Counterparties** | What is behind one golden record? | Search (case/Turkish-letter insensitive), profile with KPIs, every spelling, every source record; click a record to see the **source**: the contract clause cropped from the rendered page (full page on demand) or the spreadsheet rows with the read row highlighted |
| **Review queue** | Which extractions need a person, and why? | Works top-down (least confident first): the reason in plain words, extracted fields, source side by side, **Approve** / **Reject**, then the next record. Decided records can be **reopened** |
| **Ask the data** | Anything the dashboards don't show | Type a question (English or Turkish) or pick an example; see the rows, an automatic chart, and the SQL. Write SQL yourself. See [Text-to-SQL](#text-to-sql) |
| **Data & quality** | What does each layer hold, and how good is the pipeline? | Bronze → Silver → golden → Gold counts, status breakdown, scores against `ground_truth.json`, browsable layer tables |

### Structure: how to change or extend it

```
src/mock491/queries.py   every read the UI makes: plain functions (con, ..., tenant=None) -> DataFrame
app/main.py              navigation (PAGES) + sidebar; no page content
app/views/<page>.py      one page each: composes ui/ pieces, holds no SQL
app/ui/data.py           load(queries.fn, *args): cached, refreshed when the warehouse file changes;
                         write(action, *args) for writes such as review.decide
app/ui/components.py     page_header, kpi_row, table (standard column formats), status_badge,
                         source_viewer, field_grid, empty_state
app/ui/charts.py         Altair charts; subsidiaries keep one color everywhere
app/ui/format.py         labels (statuses, issue explanations, subsidiary names) and money formatting
app/ui/theme.py          palette per light/dark mode (validated colorblind-safe for 4 subsidiaries)
app/ui/state.py          subsidiary scope, selected counterparty, page paths for st.switch_page
```

- **New page:** add `app/views/<name>.py`, register it in `PAGES` in `main.py`, add its path to
  `state.py`, and add it to `PAGES` in `tests/test_ui.py` so it is smoke-tested.
- **New number or table:** write a function in `queries.py` (take `tenant` and filter with
  `_scope`), then `data.load(queries.your_fn, tenant)` in the page. A future API or Text-to-SQL can
  reuse the same functions.
- **New column in tables:** define its header/format once in `components.COLUMNS`. Raw codes get
  display labels through `components._DISPLAY`.
- **Restyle:** colors live in `.streamlit/config.toml` + `ui/theme.py` (keep the two in sync).
- After editing `app/ui/` modules, restart `streamlit run`: a running server can keep the old module
  in memory. Pages in `app/views/` reload on their own.
- `tests/test_ui.py` renders every page (holding-wide and scoped) on a fresh warehouse and runs
  approve → reopen through the real UI.

Not done yet: correcting a value during review (e.g. typing the right VKN, then re-resolving), and
real users/permissions. The scope selector is a view filter, not security.

## Text-to-SQL

The **Ask the data** page and `python -m mock491 ask "..."` turn a question into one SQL query over
the gold layer, run it, and show the rows **and the SQL** (report section 5; section 8, risk 3).

**Flow** (`src/mock491/genbi/`): build a sandbox → prompt the model with the table descriptions and
the curated examples → check the SQL → run it → on an error, send the error back once for a fix.

**Safety does not depend on the model behaving:**
- Each question runs in a fresh **in-memory DuckDB** that holds only four tables (`records`,
  `counterparties`, `subsidiaries`, `pending_review`), copied from the gold views and **already
  filtered to the sidebar's subsidiary**. There is no path back to the warehouse.
- The sandbox has **file and network access disabled and its configuration locked**, so even
  `read_csv(...)` or `ATTACH` fail inside it (tested).
- `guard.py` also rejects anything but a single `SELECT` over those tables, so the user sees a clear
  message instead of an engine error. Results are capped at 500 rows and 5 seconds.
- The model only sees the question and the table descriptions, never the data.

**Models** (`MOCK491_LLM`, see `config.py`):

| Setting | What happens |
|---|---|
| `auto` (default) | Uses a local **Ollama** server if one is running with `MOCK491_OLLAMA_MODEL` (default `qwen2.5-coder:7b`) pulled. Never picks a paid API. |
| `ollama` | Same, explicitly. Nothing leaves the machine. |
| `anthropic` | **Claude** (`claude-opus-5-5` by default, `MOCK491_ANTHROPIC_MODEL` to change) through the official SDK: `pip install -e ".[llm]"` plus `ANTHROPIC_API_KEY` or `ant auth login`. Server-side refusal fallback is enabled. |
| `none` | No model. |

**Without a model** the eight curated questions (`examples.py`) and hand-written SQL still work
through the same sandbox and guard. The examples also serve as few-shot examples in the prompt, and
each one is run by the tests.

Not done yet: an accuracy score for the model (a question set with expected results, like
`evaluate` does for extraction), follow-up questions that refer to earlier answers, and answers in
words beyond the model's one-line explanation.

## Environment notes

- Python **3.14** venv at `.mock491_venv`. Every dependency above installs cleanly on it.
  Docling, PaddleOCR and Splink were not tested on 3.14. If we adopt them later, check for 3.14
  support first or create a 3.12 venv.
- Windows: Turkish filenames may be stored in decomposed Unicode form. The ingest step stores
  names in NFC, and the CLI forces UTF-8 output.
