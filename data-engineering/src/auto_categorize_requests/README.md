# Auto-Categorize Help Requests Lambda (Issue #100)

Lambda that classifies help requests by `subject` and `description` into the predefined category/subcategory list (rules → embeddings → optional LLM fallback).

## Layout (per [CONTRIBUTING.md](../../CONTRIBUTING.md))

- `lambda_function.py` — entry point with `lambda_handler(event, context)`
- `classifier.py` — classification logic
- `categories_config.py` — predefined categories (align with test-saayam.netlify.app)
- `requirements.txt` — Lambda deps (openai, numpy)
- `local_test.py` — local interactive/batch testing

## Local run (from data-engineering/)

```bash
cd data-engineering
pip install -r requirements.txt
cp .env.example .env   # set OPENAI_API_KEY
python -m src.auto_categorize_requests.lambda_function   # one sample event
python -m src.auto_categorize_requests.local_test        # interactive
TEST_MODE=batch python -m src.auto_categorize_requests.local_test  # batch
```

## Notes

- Update `categories_config.py` to match the exact set of categories/subcategories used by the product.
