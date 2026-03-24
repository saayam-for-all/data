# Task Tracker — Data Engineering Team

> **Maintained by:** Project Managers (Janhavi · Ruthwik)
>
> **Update frequency:** Weekly — update statuses and assignments before each Tuesday team meeting.

---

## To-Do

<!-- PM: Update this table weekly. Move completed items to the Completed section below. -->

| Issue | Title | Assigned To | Status | Notes |
|-------|-------|-------------|--------|-------|
| [#102](https://github.com/saayam-for-all/data/issues/102) | Read and Review Data Engineering Onboarding Documentation | — | 🔄 Open | Before being assigned any development work, all new Data Engineering volunteers must read and understand the team's documentation. This is your first task. |
| [#78](https://github.com/saayam-for-all/data/issues/78) | Beginner Task: Environment Check + Saayam Practice Dataset Exploration (Local Only)  | — | 🔄 Open | Before being assigned any development work, all new Data Engineering volunteers must complete the beginner-friendly local exercise. |

---

## In Progress

<!-- PM: Update this table weekly. Move completed items to the Completed section below. -->

| Issue | Title | Assigned To | Status | Notes |
|-------|-------|-------------|--------|-------|
| [#100](https://github.com/saayam-for-all/data/issues/100) | Auto-Categorize Help Requests Using Lambda | ramumarrp77, anupbpote02, priya-2914, leoncorreia, sana-desai  | 🔄 Open | LLM-based classification. |
| [#84](https://github.com/saayam-for-all/data/issues/84) | Super Admin Dashboard Application Analytics design : creation of Test data | Datavizz31, anagha0704, batluri08, kondurvaishnavi, lokesh-jeswani | 🔄 Open |  |
| [#103](https://github.com/saayam-for-all/data/issues/103) | Daily Metrics Aggregation Lambda | Arjun2110exe, Keerthana19-p, Nitish0615, gauri-d, sanobarasna | 🔄 Open |  |
| [#104](https://github.com/saayam-for-all/data/issues/104) | Homepage Metrics Display from S3 (Web App Team)| Neharik335, PallaviP31, Srilaxmi1616, Ujwalap910 | 🔄 Open |  |
| [#114](https://github.com/saayam-for-all/data/issues/114) | Generate Synthetic CSV Data for "users" and "request" tables from Database Schema| AnushaDusakanti15, Sravy-Kolli, VeeraVSDeekshith, navyasri0820 | 🔄 Open |  |
| [#117](https://github.com/saayam-for-all/data/issues/117) | Generate Synthetic CSV Data for "volunteers_assigned"and "volunteer_details" tables from Database Schema| jeevanbanoth, priyankarao89, trikotrsh, vamisaigarapati | 🔄 Open |  |
| [#118](https://github.com/saayam-for-all/data/issues/118) | Generate Synthetic CSV Data for "volunteer_applications" and "user_skills" tables from Database Schema| emmax07, harshinianubrolu-12, sagarikapatha, shendu-95 | 🔄 Open |  |
| [#119](https://github.com/saayam-for-all/data/issues/119) | Generate Synthetic CSV Data for "request_comments" and "volunteer_rating" tables from Database Schema| Nishu2000-hub, jeminmiyani, rohitsurya7393, sanobarsana | 🔄 Open |  |
| [#120](https://github.com/saayam-for-all/data/issues/120) | Generate Synthetic CSV Data for "request_guest_details" and "req_add_info" tables from Database Schema| PoojaryAnusha98, Sindhu782, Slakkimsetty, gkswapna | 🔄 Open |  |
| [#121](https://github.com/saayam-for-all/data/issues/121) | Generate Synthetic CSV Data for "fraud_requests" and "notifications" tables from Database Schema| AbhiBadola, Bhvnikirn, Gyashaswi, pulipakav1 | 🔄 Open |  |

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
| [#99](https://github.com/saayam-for-all/data/issues/99) | Integrate Org Aggregator into Frontend | March 2026 | Cross-team (data + webapp). Lambda is done. Remaining work is React frontend integration. |

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
