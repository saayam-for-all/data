"""Build the existing filter's SQLite dictionary explicitly before packaging."""

from contextlib import closing
from pathlib import Path
import sqlite3


def create_profane_words_db(source: Path, destination: Path) -> None:
    """Load the reference word list into a new database without overwriting one."""
    words = sorted({word.strip().lower() for word in
                    source.read_text(encoding="utf-8").splitlines() if word.strip()})
    if destination.exists():
        raise FileExistsError(f"Database already exists: {destination}")
    with closing(sqlite3.connect(destination)) as conn:
        with conn:
            conn.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
            conn.executemany("INSERT INTO profane_words VALUES (?)", [(w,) for w in words])


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    create_profane_words_db(root / "bad-words.txt", root / "profane_words.db")
