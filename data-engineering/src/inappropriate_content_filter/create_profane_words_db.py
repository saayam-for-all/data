"""Build the original word-list database locally or during Lambda packaging."""

import argparse
import sqlite3
from pathlib import Path


def create_database(word_file: Path, db_path: Path) -> None:
    """Create a word-list database from a UTF-8 text file without import effects."""
    words = {
        line.strip().lower()
        for line in word_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS profane_words (words TEXT UNIQUE)")
        connection.executemany(
            "INSERT OR IGNORE INTO profane_words (words) VALUES (?)",
            [(word,) for word in sorted(words)],
        )
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    folder = Path(__file__).resolve().parent
    parser.add_argument("--word-file", type=Path, default=folder / "bad-words.txt")
    parser.add_argument("--db-path", type=Path, default=folder / "profane_words.db")
    args = parser.parse_args()
    create_database(args.word_file, args.db_path)
