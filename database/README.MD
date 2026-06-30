## Mock Data Generation

This project includes Python scripts to generate synthetic data for testing and development.

### Generate Mock Data

From the `mock-data-generation` directory, run:

```bash
python3 generate_mock_data.py
```

### Output

The generated CSV files are written to the `mock_db` directory:

- users.csv
- volunteer_applications.csv
- user_skills.csv
- request_comments.csv
- volunteer_rating.csv

### Scripts

- `generate_mock_data.py` – Main entry point that generates all CSV files.
- `volunteer_applications.py` – Generates volunteer application records.
- `user_skills.py` – Generates user skill mappings.
- `request_comments.py` – Generates request comment records.
- `volunteer_rating.py` – Generates volunteer rating records.
- `utils.py` – Shared helper functions for ID generation, timestamps, CSV writing, and random data generation.

### Custom Row Counts

The number of generated records can be changed by modifying the `count` parameter in `generate_mock_data.py`.
