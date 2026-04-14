import csv
import os
import random
import json
from datetime import datetime, timedelta

# Optional display
try:
    import pandas as pd
except ImportError:
    pd = None


# API KEY CHECK


os.environ[
    "OPENAI_API_KEY"] = "Your API Key here"
if "OPENAI_API_KEY" not in os.environ:
    raise ValueError(" Set OPENAI_API_KEY environment variable first")

# LLM
from openai import OpenAI

client = OpenAI()


# CONFIG


OUTPUT_DIR = "database/mock_db"
CACHE_FILE = "cache.json"
NUM_ROWS = 100
BATCH_SIZE = 20

random.seed(42)

USER_IDS = [str(i) for i in range(1, 101)]
REQUEST_IDS = [str(i) for i in range(1, 101)]
RATING_ENUM = ['1', '2', '3', '4', '5']



# UTILS


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def write_csv(filename, fieldnames, rows):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def random_timestamp():
    start = datetime.now() - timedelta(days=365)
    random_seconds = random.randint(0, 365 * 24 * 60 * 60)
    return (start + timedelta(seconds=random_seconds)).isoformat()



# BASE TEXT


def random_text(max_len=120):
    subjects = ["We", "The volunteer", "They", "The team"]
    verbs = ["helped", "assisted", "resolved", "handled", "managed"]
    objects = ["my issue", "the request", "the problem", "the task"]
    qualities = ["quickly", "efficiently", "professionally", "well"]

    return f"{random.choice(subjects)} {random.choice(verbs)} {random.choice(objects)} {random.choice(qualities)}."[
           :max_len]


def generate_base_reviews(n):
    return [random_text() for _ in range(n)]


def random_rating():
    return random.choice(RATING_ENUM)


def get_sentiment_label(rating):
    return {
        '5': "very positive",
        '4': "positive",
        '3': "neutral",
        '2': "negative",
        '1': "very negative"
    }[rating]



# LLM


def paraphrase_batch(text_batch, ratings_batch):
    prompt = "Rewrite each into a realistic human review with the given sentiment.\n"
    prompt += "Return ONLY one sentence per line.\n\n"

    for i, (text, rating) in enumerate(zip(text_batch, ratings_batch)):
        sentiment = get_sentiment_label(rating)
        prompt += f"{i + 1}. Sentiment: {sentiment}\n{text}\n\n"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9
    )

    raw_lines = response.choices[0].message.content.strip().split("\n")

    lines = []
    for line in raw_lines:
        line = line.strip()
        if line:
            line = line.split(".", 1)[-1].strip()
            lines.append(line)

    #  Ensure same length (critical fix)
    while len(lines) < len(text_batch):
        lines.append(text_batch[len(lines)])  # fallback

    return lines[:len(text_batch)]


def process_in_batches(texts, ratings):
    results = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i:i + BATCH_SIZE]
        batch_ratings = ratings[i:i + BATCH_SIZE]

        results.extend(paraphrase_batch(batch_texts, batch_ratings))

    return results



# CACHE


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def cached_paraphrase(texts, ratings):
    cache = load_cache()
    results = []

    new_texts, new_ratings = [], []

    for t, r in zip(texts, ratings):
        key = f"{t}|{r}"
        if key in cache:
            results.append(cache[key])
        else:
            new_texts.append(t)
            new_ratings.append(r)

    if new_texts:
        paraphrased = process_in_batches(new_texts, new_ratings)

        for t, r, p in zip(new_texts, new_ratings, paraphrased):
            cache[f"{t}|{r}"] = p
            results.append(p)

    save_cache(cache)
    return results



# PIPELINE


def generate_realistic_reviews(n):
    base = generate_base_reviews(n)
    ratings = [random_rating() for _ in range(n)]

    unique_pairs = list(set(zip(base, ratings)))
    texts = [x[0] for x in unique_pairs]
    rts = [x[1] for x in unique_pairs]

    enhanced = cached_paraphrase(texts, rts)

    final_reviews, final_ratings = [], []

    for _ in range(n):
        idx = random.randint(0, len(enhanced) - 1)
        final_reviews.append(enhanced[idx])
        final_ratings.append(rts[idx])

    return final_reviews, final_ratings



# DATA GENERATION


def generate_request_comments(n, reviews):
    rows = []
    for i in range(1, n + 1):
        ts = random_timestamp()
        rows.append({
            "comment_id": i,
            "req_id": random.choice(REQUEST_IDS),
            "commenter_id": random.choice(USER_IDS),
            "comment_desc": reviews[i - 1],
            "created_at": ts,
            "last_updated_at": ts,
            "isdeleted": False
        })
    return rows


def generate_volunteer_rating(n, reviews, ratings):
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "volunteer_rating_id": i,
            "user_id": random.choice(USER_IDS),
            "request_id": random.choice(REQUEST_IDS),
            "rating": ratings[i - 1],
            "feedback": reviews[i - 1],
            "last_update_date": random_timestamp()
        })
    return rows



# DISPLAY


def display_with_pandas():
    if pd is None:
        return

    df_comments = pd.read_csv(f"{OUTPUT_DIR}/request_comments.csv")
    df_ratings = pd.read_csv(f"{OUTPUT_DIR}/volunteer_rating.csv")

    print("\n📊 Request Comments (20 rows):")
    print(df_comments.head(20).to_string(index=False))

    print("\n📊 Volunteer Ratings (20 rows):")
    print(df_ratings.head(20).to_string(index=False))


# MAIN


def main():
    ensure_output_dir()

    print(" Generating LLM-powered reviews...")
    reviews, ratings = generate_realistic_reviews(NUM_ROWS)

    request_comments = generate_request_comments(NUM_ROWS, reviews)
    volunteer_rating = generate_volunteer_rating(NUM_ROWS, reviews, ratings)

    write_csv("request_comments.csv", request_comments[0].keys(), request_comments)
    write_csv("volunteer_rating.csv", volunteer_rating[0].keys(), volunteer_rating)

    print("Data generated successfully!")

    display_with_pandas()


if __name__ == "__main__":
    main()
