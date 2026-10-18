"""Create profane_words.db from a word-list file.

Usage (PowerShell):
    py build.py                    (reads words_profanity.txt)
    py build.py other.txt          (reads another file)

The file should have one word or phrase per line.
Blank lines and lines starting with # are skipped.
"""

import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WORD_FILE = os.path.join(HERE, "words_profanity.txt")
DB_PATH = os.path.join(HERE, "profane_words.db")      # same folder as lambda_function.py
def read_words(path):
    """Read one word per line: lowercase, trim spaces, skip blanks and # comments."""
    with open(path, encoding="utf-8") as f:
        words = {line.strip().lower() for line in f}
    return sorted(w for w in words if w and not w.startswith("#"))


def build(words, db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE IF EXISTS profane_words")      # rebuild from scratch each time
    conn.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
    conn.executemany("INSERT INTO profane_words (words) VALUES (?)", [(w,) for w in words])
    conn.commit()
    conn.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_WORD_FILE

    if not os.path.exists(path):
        sys.exit(f"Error: {path} not found. Put it in this folder or pass a path.")

    words = read_words(path)
    if not words:
        sys.exit(f"Error: {path} has no words (only blanks or comments).")

    build(words)
    print(f"Read {len(words)} words from {path}")
    print(f"Database created: {DB_PATH}")