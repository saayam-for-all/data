# Mock Data Generation — Saayam Database

This folder contains Python scripts to generate synthetic (mock) CSV data for the Saayam platform database tables. The generated CSVs are stored in `/database/mock_db/`.

---

## 📁 Files in This Folder

| File | Description |
|------|-------------|
| `generate_fraud_requests.py` | Generates mock data for the `fraud_requests` table |
| `generate_notifications.py` | Generates mock data for the `notifications` table |
| `db_info.json` | Full schema definition for all Saayam database tables |
| `README.md` | This file |

---

## 📦 Prerequisites

Python 3.8+ required. Install dependencies:

```bash
pip install faker pandas
```

---

## 🚀 How to Run

### Generate `fraud_requests.csv` (default: 800 rows)

```bash
python generate_fraud_requests.py
```

**Options:**
```bash
python generate_fraud_requests.py --rows 800 --output fraud_requests.csv
```

---

### Generate `notifications.csv` (default: 30,000 rows)

```bash
python generate_notifications.py
```

**Options:**
```bash
python generate_notifications.py --rows 30000 --output notifications.csv
```

To scale up to 40,000+ rows:
```bash
python generate_notifications.py --rows 40000 --output notifications_40k.csv
```

---

## 📊 Output Files

All generated CSVs should be saved to `/database/mock_db/`.

| File | Rows | Columns | Table |
|------|------|---------|-------|
| `fraud_requests.csv` | 800 | 4 | `fraud_requests` |
| `notifications.csv` | 30,000 | 8 | `notifications` |

---

## 🗂️ Schema Details

### `fraud_requests`
| Column | Type | Notes |
|--------|------|-------|
| `fraud_request_id` | integer | Primary key, auto-incremented |
| `user_id` | varchar(255) | FK → users table |
| `request_datetime` | timestamp | Range: 2022–2025 |
| `reason` | varchar(255) | 20 realistic fraud reason templates |

### `notifications`
| Column | Type | Notes |
|--------|------|-------|
| `notification_id` | integer | Primary key, auto-incremented |
| `user_id` | varchar(255) | FK → users table |
| `type_id` | integer | FK → notification_types (1–6) |
| `channel_id` | integer | FK → notification_channels (1–4) |
| `message` | text | Type-specific realistic message templates |
| `status` | enum | sent / delivered / read / failed |
| `created_at` | timestamp | Range: 2022–2025 |
| `last_update_date` | timestamp | Always ≥ created_at |

---

## 🔗 Foreign Key References

### notification_types (type_id)
| ID | Name |
|----|------|
| 1 | Volunteer Match |
| 2 | Help Request Update |
| 3 | System Alert |
| 4 | New Message |
| 5 | Account Activity |
| 6 | Community Announcement |

### notification_channels (channel_id)
| ID | Name |
|----|------|
| 1 | Email |
| 2 | SMS |
| 3 | Push Notification |
| 4 | In-App |

---

## 🔁 Scalability

Both scripts are parameterized and can be scaled up easily:

```bash
# Scale fraud_requests to 5,000 rows
python generate_fraud_requests.py --rows 5000

# Scale notifications to 40,000 rows
python generate_notifications.py --rows 40000
```

Scripts use `random.seed(42)` and `Faker.seed(42)` for reproducibility — running the same command twice produces the same output.

---

## ✅ Data Quality Notes

- **Zero nulls** across all generated fields
- **FK integrity**: user_ids are drawn from a consistent pool of 500 synthetic users
- **Realistic distributions**: notification status weighted (55% read, 25% delivered, 15% sent, 5% failed)
- **Date consistency**: `last_update_date` is always equal to or after `created_at`
- **Message content**: type-specific templates ensure messages are contextually appropriate

---

## 📌 Schema Source

Full schema available in `db_info.json` in this folder, and in `Saayam_Table_column_names_data.xlsx` in the `/database/` folder.
