# ingestion-pipeline

Shared ingestion lanes for DocMap Intelligence OS. Every lane follows the same
contract (see `docs/DATA_INGESTION_PLANS.md`):

1. Parse raw exports from `data/imports/` into the common staging envelope.
2. Stage normalized JSONL in `data/staging/` (deduped by `source_id`).
3. Sync staged records to Supabase metadata tables + `document_embeddings`.
4. Log every run to `data_ingestion_runs`.

## Install (dev)

```bash
pip install -e ./ingestion-pipeline
```

## Usage

```bash
python -m ingestion_pipeline sync clinic-csv --dry-run   # P4 clinic seed, no writes
python -m ingestion_pipeline sync clinic-csv             # parse + stage + Supabase
python -m ingestion_pipeline sync all --dry-run          # all lanes, counts only
python -m ingestion_pipeline review list                 # pending human reviews
python -m ingestion_pipeline review approve <source_id>
python -m ingestion_pipeline review reject <source_id>
```

Lanes shipped so far: `clinic_csv` (P4). Transcript/email lanes (P1–P3) follow
the same envelope — add a parser under `lanes/` and a writer under `sync/`.
