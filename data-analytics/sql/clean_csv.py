#!/usr/bin/env python3
"""
clean_csv.py <input.csv> <output.csv>

Reads a CSV and rewrites any field whose value is exactly the literal
text "NULL" (case-sensitive, ignoring surrounding whitespace) as a true
empty field. Leaves every other field untouched. Uses Python's csv
module so quoting/commas-inside-quotes are handled correctly.
"""
import csv
import sys

def main():
    if len(sys.argv) != 3:
        print("Usage: clean_csv.py <input.csv> <output.csv>")
        sys.exit(1)

    src, dst = sys.argv[1], sys.argv[2]

    with open(src, newline="", encoding="utf-8") as fin, \
         open(dst, "w", newline="", encoding="utf-8") as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)
        for row in reader:
            cleaned = ["" if (cell is not None and cell.strip() == "NULL") else cell for cell in row]
            writer.writerow(cleaned)

if __name__ == "__main__":
    main()
