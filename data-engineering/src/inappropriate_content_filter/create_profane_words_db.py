import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))


def create_profane_words_db(words_path=os.path.join(HERE, "bad-words.txt"),
                            db_path=os.path.join(HERE, "profane_words.db")):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create the table
    cursor.execute("CREATE TABLE IF NOT EXISTS profane_words (words TEXT UNIQUE)")

    with open(words_path, encoding="utf-8") as f:
        bad_words = [word.strip().lower() for word in f.read().splitlines() if word.strip()]

    # Insert words into the table
    cursor.executemany("INSERT OR IGNORE INTO profane_words (words) VALUES (?)", [(word,) for word in bad_words])

    # Commit and close
    conn.commit()
    conn.close()


# Build profane_words.db next to the Lambda before packaging it
if __name__ == "__main__":
    create_profane_words_db()
