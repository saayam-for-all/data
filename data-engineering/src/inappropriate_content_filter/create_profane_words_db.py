import sqlite3

def create_profane_words_db():
    conn = sqlite3.connect("profane_words.db")
    cursor = conn.cursor()

    # Create the table
    cursor.execute("CREATE TABLE IF NOT EXISTS profane_words (words TEXT UNIQUE)")

    # List of bad words
    # bad_words = ["badword1", "badword2", "badword3"]  # Replace with actual words
    with open('bad-words.txt') as f:
        bad_words = f.read().splitlines()

    # Insert words into the table
    cursor.executemany("INSERT OR IGNORE INTO profane_words (words) VALUES (?)", [(word,) for word in bad_words])

    # Commit and close
    conn.commit()
    conn.close()

# Call the function to create the database
create_profane_words_db()
