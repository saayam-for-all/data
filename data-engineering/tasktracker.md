# Task Tracker — Data Engineering Team

> **Maintained by:** Project Managers (Janhavi · Ruthwik)
>
> **Update frequency:** Weekly — update statuses and assignments before each Tuesday team meeting.

---

## In Progress

<!-- PM: Update this table weekly. Move completed items to the Completed section below. -->

| Issue | Title | Assigned To | Status | Notes |
|-------|-------|-------------|--------|-------|
| [#99](https://github.com/saayam-for-all/data/issues/99) | Integrate Org Aggregator into Frontend | — | 🔄 Open | Cross-team (data + webapp). Lambda is done. Remaining work is React frontend integration. |
| [#100](https://github.com/saayam-for-all/data/issues/100) | Auto-Categorize Help Requests Using Lambda | ramumarrp77, anupbpote02 | 🔄 Open | LLM-based classification. |

> **Note:** Many issues in the #80-90 range are stale — created by volunteers who are no longer active. These need triage (reassign or close).

---

## Completed

<!-- PM: When moving items here, add the completion date. Technical details for completed work live in KNOWLEDGE_TRANSFER.md. -->

| Issue | Title | Completed | Notes |
|-------|-------|-----------|-------|
| [#98](https://github.com/saayam-for-all/data/issues/98) | Aggregate Organization Listings from Multiple Sources | Feb 2026 | Lambda deployed. See [KNOWLEDGE_TRANSFER.md](KNOWLEDGE_TRANSFER.md) for specs. |
| [#57](https://github.com/saayam-for-all/data/issues/57) | ETL Architecture Design | 2025 | Informed current pipeline. |
| [#56](https://github.com/saayam-for-all/data/issues/56) | Aurora Schema for Nonprofits | 2025 | Schema defined. |
| [#55](https://github.com/saayam-for-all/data/issues/55) | AWS Architecture Document | 2025 | Informed current pipeline. |
| [#62](https://github.com/saayam-for-all/data/issues/62) | Charity Navigator Scraper | 2025 | Completed. |
| [#60](https://github.com/saayam-for-all/data/issues/60) | IRS S3 Lambda | 2025 | IRS data later dropped. |
| [#67](https://github.com/saayam-for-all/data/issues/67) | IRS Nonprofit Categorization | 2025 | IRS data later dropped. |
| — | Emergency Contact Data Pipeline | 2025 | Wikipedia → clean → PostgreSQL. |
| — | NGO Web Scrapers | 2025 | Afghanistan, India, Malaysia. CSVs, not yet automated. |
| — | Language Detection & Translation | 2025 | `langdetect` + `GoogleTranslator`. |
| — | Fraud Detection Model (Schema Only) | 2025 | SQLAlchemy model only, no detection logic. |

---

## Roadmap

<!-- PM: Reorder by priority as needed. Add new items as they come up in team meetings. -->

| Priority | Item | Details | Status |
|----------|------|---------|--------|
| 1 | RDBMS → S3 Data Lake | Periodic data export from Aurora to S3. Needs functional spec. | Not started |
| 2 | Data Vectorization | Generate embeddings from exported data. Tech selection needed. | Not started |
| 3 | Vector DB Setup | Evaluate Pinecone, Weaviate, pgvector, etc. | Not started |
| 4 | Saayam AI Agent | Agent that queries vector DB with Saayam's own data. | Not started |
| 5 | Content Safety | Sentiment analysis (#87), translation for content filtering (#86). | Stale |
| 6 | Analytics Dashboard | Super Admin analytics (#81-89). Data Analytics team scope. | Stale |

These align with Rao's long-term directive:

```
PostgreSQL (RDBMS) → S3 Data Lake → Vectorize → Vector DB → AI Agent
```

---

*Last updated: February 2026*
