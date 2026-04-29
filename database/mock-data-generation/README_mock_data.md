# Synthetic Data Generator — Issue #119

**Tables:** `request_comments`, `volunteer_rating`  
**Script:** `generate_119.py`  
**Branch:** `Nishu2000-hub_feature/synthetic-data-119`  
---

## Problem

Saayam For All's `request_comments` and `volunteer_rating` tables are empty (cold start).

This script generates realistic synthetic CSV data for both tables — 100 rows by default, scalable to 40,000+ — with full schema compliance, referential integrity, and ML-training-grade text diversity.

---

## Quick Start

```bash
# Default: 100 rows per table
python generate_119.py

# Scale to 40,000 rows
python generate_119.py --rows 40000

# Custom seed for reproducibility
python generate_119.py --rows 40000 --seed 123

# With real FK values from other team's CSVs (preferred)
python generate_119.py \
  --users-csv database/mock_db/users.csv \
  --requests-csv database/mock_db/request.csv
```

**Zero external dependencies.** Uses only Python builtins: `csv`, `random`, `uuid`, `datetime`, `re`, `argparse`.

### Output

```
database/mock_db/request_comments.csv
database/mock_db/volunteer_rating.csv
```

### CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--rows` | 100 | Rows per table |
| `--pool-size` | `max(200, rows×3)` | Internal user/request pool size |
| `--seed` | 42 | Random seed for reproducibility |
| `--users-csv` | None | Path to external `users.csv` for real FK integrity |
| `--requests-csv` | None | Path to external `request.csv` for real FK integrity |

---

## Category Hierarchy — Official Schema

Category IDs use **materialized path notation** from the official `help_categories` table.

**Source:** [1.0 MVP Help Categories Wiki](https://github.com/saayam-for-all/request/wiki/1.0-MVP-Help-Categories,-Additional-Fields-&-their-Metadata)  

| Parent cat_id | Category | Leaf examples |
|---------------|----------|---------------|
| `1` | FOOD_AND_ESSENTIALS | `1.1` Food Assistance, `1.2` Grocery, `1.3.1`–`1.3.5` Cooking Help |
| `2` | CLOTHING_ASSISTANCE | `2.1` Donate, `2.2` Borrow, `2.3` Emergency, `2.4` Tailoring |
| `3` | HOUSING_ASSISTANCE | `3.1` Lease, `3.2` Rent, `3.3.1`–`3.3.13` Repair/Maintenance, `3.4`–`3.10` |
| `4` | EDUCATION_CAREER_SUPPORT | `4.1` College App, `4.2` SOP, `4.3.1`–`4.3.6` Tutoring, `4.4`–`4.7` |
| `5` | HEALTHCARE_AND_WELLNESS | `5.1.1`–`5.1.11` Medical Consultation, `5.2`–`5.5` |
| `6` | ELDERLY_COMMUNITY_ASSISTANCE | `6.1`–`6.9` |
| `0.0.0.0.0` | GENERAL_CATEGORY | General fallback |

**87 total entries** mirrored 1:1 from the wiki. Only **leaf nodes** are valid for `req_cat_id` — requests are filed under the most specific subcategory.

### Category Distribution Weights

| cat_id | Category | Weight |
|--------|----------|--------|
| `1` | Food & Essentials | 22% |
| `5` | Healthcare & Wellness | 20% |
| `4` | Education & Career | 18% |
| `3` | Housing Assistance | 17% |
| `6` | Elderly Community | 10% |
| `2` | Clothing Assistance | 8% |
| `0.0.0.0.0` | General | 5% |

---

## Text Generation — 3-Tier Pipeline

The original approach used ~40 fixed comment templates. At 40,000 rows, each template repeats ~1,000 times — an ML model trained on that learns string hashes, not language. The 3-tier pipeline solves this.

### Tier 1 — Compositional Grammar

Each comment is assembled from **4 independent slots**:

```
[greeting] + [action] + [timing] + [followup]
```

Each feedback entry is assembled from **3 slots** + optional category context:

```
[opener] + [detail] + [recommend]   (+ 40% chance: category-specific prefix)
```

Every slot has 10–32 unique variants per category. The combinatorial math:

- Comments: `15 × 12 × 18 × 12 = 38,880` unique base combinations per category × 7 categories
- Feedback: `24 × 32 × 20 = 15,360` unique bases for 5-star alone

Slots are **category-unique** — no greeting, followup, or timing phrase is shared across categories, preventing cross-category 4-gram collisions.

### Tier 2 — Stochastic Perturbation

Applied to every composed string at runtime:

| Perturbation | Rate | Purpose |
|-------------|------|---------|
| Synonym replacement | 30% per match | Breaks repeated phrasing (`"arranged"` → `"coordinated"` / `"set up"` / `"lined up"`) |
| Temporal detail injection | 10% | Swaps vague timing (`"soon"`) with specific day/time (`"on Tuesday morning"`) |
| Typo injection | 2% | Realism — real users make typos |
| Punctuation variation | 15% | `.` → `!` / `!!` / `:)` / `...` |
| Casing variation | 8% | Some users type all lowercase |

**35-entry synonym map** covers verbs, adjectives, and structural phrases across both comments and feedback.

### Tier 3 — Diversity Validator

Automated diagnostics run after every generation pass:

```
Diversity — comment_desc text
   Total texts        : 40,000
   Unique texts       : 37,530  (93.8%)  OK
   Unique 4-grams     : 23,880
   Max 4-gram freq    : 2.25%  HIGH — most repeated:
     Most common      : health update for you: (902×)
```

**Checks:**

- **Unique string ratio** — target ≥ 80%. Measures raw deduplication.
- **Max 4-gram frequency** — target ≤ 2%. Prevents any phrase pattern from dominating the corpus. If a model can learn to predict the next word from a 4-gram that appears in >2% of rows, it's memorizing, not generalizing.

If either threshold fails, the validator flags the exact phrase responsible so it can be fixed.

---

## Schema Details

### request_comments

| Column | Type | Source |
|--------|------|--------|
| `comment_id` | integer (PK) | Sequential, 1-indexed |
| `req_id` | string (FK) | From internal pool or `--requests-csv` |
| `commenter_id` | string (FK) | 75% volunteer (random user), 25% requester (follow-up) |
| `comment_desc` | string | Tier 1 + Tier 2 generated text |
| `created_at` | datetime | Within 30 days after request creation |
| `last_updated_at` | datetime | Within 72 hours after comment creation |
| `isdeleted` | boolean | 5% TRUE (soft delete simulation) |

### volunteer_rating

| Column | Type | Source |
|--------|------|--------|
| `volunteer_rating_id` | integer (PK) | Sequential, 1-indexed |
| `user_id` | string (FK) | From internal pool or `--users-csv` |
| `request_id` | string (FK) | From internal pool or `--requests-csv` |
| `rating` | integer (1–5) | Weighted: 45% five-star, 33% four-star, 12% three, 6% two, 4% one |
| `feedback` | string | Tier 1 + Tier 2 generated text, sentiment-matched to rating |
| `last_update_date` | datetime | 1 hour to 14 days after request creation |

### Integrity Guarantees

- Zero PK duplicates at any scale (validated at 100 and 40,000 rows)
- Zero null PKs
- Zero duplicate `(user_id, request_id)` pairs in `volunteer_rating`
- Timestamps are chronologically valid: `request.created_at < comment.created_at < comment.last_updated_at`
- Rating distribution matches real-world volunteer feedback patterns

---

## Validated Metrics at 40,000 Rows

| Metric | Comments | Feedback | Target |
|--------|----------|----------|--------|
| Unique string ratio | 93.8% | 88.7% | ≥ 80% |
| Unique 4-grams | 23,880 | 23,210 | — |
| Max 4-gram frequency | ~2.3% | ~2.0% | ≤ 2% |
| PK duplicates | 0 | 0 | 0 |
| Null PKs | 0 | 0 | 0 |
| Duplicate user-request pairs | — | 0 | 0 |

---

## FK Integration with Other Teams

When the users and requests teams deliver their CSVs:

```bash
python generate_119.py \
  --users-csv database/mock_db/users.csv \
  --requests-csv database/mock_db/request.csv \
  --rows 40000
```

This regenerates both files using real `user_id` and `req_id` values — full cross-table FK consistency across the entire synthetic dataset.

The loader handles column name variants automatically (e.g., `req_id` / `request_id`, `created_at` / `req_created_at`) and maps both old human-readable category names and official `cat_id` values.

---

---

## File Structure

```
database/mock-data-generation/
├── generate_119.py          # Main script
├── README.md                # This file
└── ...

database/mock_db/            # Generated output
├── request_comments.csv
└── volunteer_rating.csv
```

---

## Reproduction

```bash
# Exact reproduction (deterministic with seed)
python generate_119.py --rows 40000 --seed 42

# Verify output
# Script prints validation + diversity diagnostics automatically
```

Every run with the same `--seed` and `--rows` produces identical output.
