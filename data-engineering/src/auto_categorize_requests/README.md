# Auto-Categorize Help Requests Lambda (Issue #100)

Lambda that classifies help requests by `subject` and `description` into predefined category/subcategory (rules → embeddings → LLM fallback). Matches repo convention: same folder name and branch pattern as [srilaxmi1616_100_auto_categorize_requests](https://github.com/saayam-for-all/data/tree/srilaxmi1616_100_auto_categorize_requests).

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

## Branch and PR (same as other contributor)

**Branch name:** `<YOUR_GITHUB_USERNAME>_100_auto_categorize_requests`  
**Folder:** `data-engineering/src/auto_categorize_requests/`

1. Branch off `dev`:
   ```bash
   git fetch origin
   git checkout dev
   git pull origin dev
   git checkout -b YOUR_GITHUB_USERNAME_100_auto_categorize_requests
   ```

2. Stage and commit:
   ```bash
   git add data-engineering/src/__init__.py
   git add data-engineering/src/auto_categorize_requests/
   git commit -m "#100: Add Lambda to auto-categorize help requests"
   ```

3. Push and open PR targeting **dev**:
   ```bash
   git push -u origin YOUR_GITHUB_USERNAME_100_auto_categorize_requests
   ```
   On GitHub: New PR → base **dev**, compare your branch. Put "Closes #100" in the description. Assign reviewers (≥2).
