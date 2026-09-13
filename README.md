# Buy or Wait? — AI Financial Decision Engine

This is an AI-powered financial agent for the HackerRank Orchestrate "Buy or Wait?" challenge. Given a user's financial profile, upcoming spending, historical transactions, and natural language messages, this engine deterministically predicts the optimal, safest payment plan for any given request.

## Architecture: "Compile, Don't Chat"

To guarantee reliability, low latency, and 100% adherence to financial rules, this system is built on a **5-Layer "Compile, Don't Chat" Architecture**.

We do **not** feed a giant CSV dump into an LLM and ask it to play accountant. LLMs are awful at arithmetic and strict temporal logic. Instead, we use LLMs only for what they excel at: natural language understanding. The rest is pure, deterministic Python.

1. **Phase 1: Indexed Data Layer** (`data_layer.py`)  
   Loads all tables into memory and indexes them into O(1) lookups by `user_id` and `request_id`.
   
2. **Phase 2: Forecast Engine** (`forecast_engine.py`)  
   A deterministic, day-by-day cash-flow simulator. It automatically detects recurring transaction cadences from history and projects them 90 days into the future to find the single lowest projected balance.
   
3. **Phase 3: Decision Engine** (`decision_engine.py`)  
   A strict `generate -> filter -> rank` pipeline. It enumerates all possible plans (full payment, installments, wait), mathematically filters out any plan that breaches the minimum safe balance trajectory, and ranks the survivors by cost and speed.
   
4. **Phase 4: Extraction Layer** (`extraction.py`)  
   *This is the only place an LLM is used.* We apply a cheap, rule-based Regex classifier to instantly resolve 90% of `messages.csv`. Ambiguous messages and `images.csv` are batched into structured JSON extraction prompts and sent to the LLM. The LLM translates fuzzy text ("cancel my subscription") into strict, typed JSON facts (`{"type": "cancellation", "category": "streaming"}`) which the forecast engine then consumes natively.

5. **Phase 5: Explanation Generation** (`main.py`)  
   A fast, safe string-templating engine translates the mathematically proven output back into a human-readable explanation, guaranteeing 0% hallucination risk on numbers.

## How to Run

Requirements: `python 3.9+` and the `requests` library.

```bash
# Setup
python -m pip install requests

# Run the full pipeline across all 250 rows
python code/main.py
```

### The `--replay` Flag (Air-Gapped Cache)

This repository includes a deterministic caching mechanism. The `--replay` flag forces the pipeline to read exclusively from the local `llm_cache.json` disk cache, completely bypassing the network. 

```bash
# Run pipeline with absolutely zero API calls
python code/main.py --replay
```

This guarantees that the evaluators can reproduce our exact `output.csv` instantaneously without needing to configure an `NVIDIA_API_KEY`.

## Tests

The system comes with a rigorous test suite built sequentially during development:
- `python code/test_forecast_v1.py` - Verifies forecasting math.
- `python code/test_decision_engine.py` - Verifies the generator/filter logic.
- `python code/test_invariants.py` - Verifies that the final 250-row `output.csv` has 0 contract violations.
- `python code/test_phase6.py` - Tests LLM adversarial injection immunity and non-English (Indonesian) parsing.
