# Evaluation Protocol

The evaluation protocol is part of the product. It exists to prevent the most
common failure mode in fine-tuning demos: reporting a high score from a split
that leaked duplicates into training.

## Dataset

The generator is deterministic (`SEED=42`) and defined in
`scripts/generate_dataset_v3.py`.

| Metric | Value |
|---|---|
| Raw synthetic rows | 11,510 |
| Unique examples after canonical deduplication | 4,285 |
| Duplicates removed | 7,225 |
| Template families | 19 |
| Manual challenge prompts | 64 |
| Schema-invalid rows after audit | 0 |
| Tool mix | EC2 6,586 / RDS 2,680 / Billing 2,244 |

The canonical deduplication key is `(prompt, tool name, sorted arguments)`.
Deduplication happens **before** splitting.

## Splits

The seeded 80/10/10 split operates on the 4,285 unique examples:

| Split | Examples |
|---|---|
| Train | 3,428 |
| Validation | 429 |
| Test | 428 |
| Train/test overlap | 0 |

Training and evaluation call the same split function,
`scripts/training/pipeline_utils.build_splits`, so the test partition cannot
silently change between phases. Every run reports the effective seed, split
sizes, duplicate count and overlap.

## Challenge set

`data/challenge_set.jsonl` contains 64 manually authored prompts that do not
come from generator templates. It covers:

- cities and regions;
- ambiguous instructions;
- noise and typos;
- Spanglish;
- unknown instance types;
- read-only billing requests.

The challenge set has zero overlap with the training prompts. It is tracked in
git; the 11,510-row training set is generated locally and gitignored.

## Evaluation modes

`scripts/training/eval.py` supports four modes. Always report the mode next to
the score.

| Mode | What it measures |
|---|---|
| `standard` | In-distribution performance on the deduplicated split |
| `template` | Unseen phrasing: complete template families held out |
| `unseen` | Unseen values: configured regions/ports/types appear only in test |
| `challenge` | Unseen language: the 64 manual prompts |

A consistency gate compares the evaluation split mode and effective seed with
the checkpoint's `dataset_metadata.json`; mismatches are refused. Reports are
written as `eval_report_<mode>.json` next to the adapter.

## Quick eval

`arcops --eval` runs five built-in cases with greedy decoding. It is a smoke
test, not a benchmark.

| Metric | Result |
|---|---|
| Tool selection | 5/5 (100%) |
| Field accuracy | 6/11 (54.5%) |
| Exact match | 2/5 (40%) |

The result is useful as a regression check: it catches a broken adapter or a
bad prompt template. It is not evidence of production accuracy.

## Results policy

- **No checkpoint is shipped** in the repository. The public adapter is
  `CodeSantiago/arcops`.
- Historical "100%" numbers were measured on a split that leaked duplicates and
  are not trustworthy.
- The current pipeline deduplicates before splitting, groups by template family
  and enforces the consistency gate.
- Run `eval.py` against your own adapter and report the mode. Do not compare
  scores across modes.
- A high tool-selection score with low field accuracy is common on vague
  prompts; both numbers matter.

## Reproduce

```bash
# Regenerate the dataset (deterministic)
python scripts/generate_dataset_v3.py

# Quick smoke eval (requires the model)
arcops --eval

# Full evaluation against an adapter
python scripts/training/eval.py --checkpoint checkpoints/final

# Template holdout
python scripts/training/eval.py \
  --checkpoint checkpoints/final \
  --eval-mode template \
  --test-families ec2_ports,rds_failover

# Unseen values
python scripts/training/eval.py \
  --checkpoint checkpoints/final \
  --eval-mode unseen \
  --unseen region=ap-northeast-1,ca-central-1 \
  --unseen port=6379

# Manual challenge set
python scripts/training/eval.py \
  --checkpoint checkpoints/final \
  --eval-mode challenge
```

## Dataset audit

The packaged JSON Schemas are the same ones used at runtime. A local audit runs
`jsonschema` over every row:

- all 11,510 rows validate after the `instance_type` pattern was widened to
  accept real AWS families such as `c6i`, `t4g` and `m7g`;
- unknown instance types are still blocked at runtime by the priced/safety
  allowlist in `cloudops_fc.safety`.

## Limitations

- English-only synthetic data; Spanish and multi-turn conversations are not
  covered.
- The dataset is generated, not collected from real incidents.
- The 7B model is evaluated on a 12 GB consumer GPU; results may differ on
  other hardware or quantization settings.
- The TUI has no automated coverage; evaluation covers the engine, not the
  dashboard rendering.
