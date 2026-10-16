"""One-time local setup: builds profane_words.db from bad-words.txt.

Run with `python create_profane_words_db.py` from this directory, or
`python create_profane_words_db.py /some/dir` to write the DB elsewhere
(matches PROFANE_WORDS_DB in lambda_function.py, which defaults to this
directory).
"""
import os
import sqlite3
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_profane_words_db(output_dir=None):
    output_dir = output_dir or _MODULE_DIR
    db_path = os.path.join(output_dir, "profane_words.db")
    words_path = os.path.join(_MODULE_DIR, "bad-words.txt")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS profane_words (words TEXT UNIQUE)")
        with open(words_path) as f:
            bad_words = f.read().splitlines()
        cursor.executemany(
            "INSERT OR IGNORE INTO profane_words (words) VALUES (?)",
            [(word,) for word in bad_words],
        )
        conn.commit()
    finally:
        conn.close()
    print(f"Wrote {len(bad_words)} words to {db_path}")


if __name__ == "__main__":
    create_profane_words_db(sys.argv[1] if len(sys.argv) > 1 else None)
