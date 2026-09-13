# Usage Report

This file summarizes the language model usage for the entire pipeline run across all 250 requests in `requests.csv`.

## Models Used

1. **Text Extraction & Routing:** `meta/llama-3.3-70b-instruct`
2. **Image Parsing (Receipts/Checks):** `meta/llama-3.2-11b-vision-instruct`

## Aggregated Usage

The pipeline successfully executed on all 250 rows. 

- **Total API Calls**: 14 (13 Text, 1 Vision)
- **Total Calls Served from Cache**: 14
- **Cache Hit Rate**: 100%

Because the pipeline was run using the `--replay` flag, **0 new API calls were made during the final run**. 100% of the required intelligence extraction was served locally from the `llm_cache.json` air-gapped cache, guaranteeing deterministic behavior and zero network dependency.

### Breakdown by Model

#### `meta/llama-3.3-70b-instruct`
- **Total Calls**: 13
- **Calls from Cache**: 13
- **Estimated Prompt Tokens**: ~6,500
- **Estimated Completion Tokens**: ~650
- **Cost**: ~$0.00 (NVIDIA API / Free Tier / Negligible)

#### `meta/llama-3.2-11b-vision-instruct`
- **Total Calls**: 1
- **Calls from Cache**: 1
- **Estimated Prompt Tokens**: ~200
- **Estimated Completion Tokens**: ~20
- **Cost**: ~$0.00

## Notes
- Rule-based fast paths in `extraction.py` effectively handled the vast majority of standard `messages.csv` rows (e.g. cancellations, simple confirmations) without invoking any LLM, achieving massive cost reduction.
- Only the ambiguous or complex natural language rows were batched and sent to the LLM.
