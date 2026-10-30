# §1 Scope and method

This documentation serves as an audited operational reference for the codebase hosted within `saayam-for-all/data`[cite: 2]. Rather than reiterating original design intent, the specifications here reflect the verified state of the deployed data infrastructure, traceable directly to repository code, workflow configurations, and active database schemas[cite: 2].

### Service Boundaries
The Data Engineering & Analytics microservice encompasses the following components:
* **Analytics & Reporting Modules:** The core analytics handler (`kpi_api_analytics.py`) and top-level web execution endpoints (`main.py`, `app.py`)[cite: 1, 2].
* **Serverless Execution Units:** Isolated AWS Lambda modules under `data-engineering/src/` including `saayam-org-aggregator`, `categorizer`, and `aggregate-daily-metrics`[cite: 1, 2].
* **Data Ingestion & Support Pipelines:** Automated ingestion tools within `scrapers/` and multilingual text processing under `translation/`[cite: 1, 2].
* **Shared Technical Foundations:** Common data access abstractions and entity models maintained in `utils/` and `models/`[cite: 1, 2].

*Out of Scope:* Infrastructure-level API Gateway routing, network firewalls, and Cognito identity management are managed by the core platform team and detailed in platform-level documentation[cite: 2].

### Recent Engineering Changes
Material updates pulled from merged pull requests and commit logs are recorded below to establish a baseline for integrators holding earlier specifications[cite: 2, 3]:

| Change | Date | Technical Impact |
| :--- | :--- | :--- |
| **Organization Analytics Endpoint Expansion (`#228`)** | 18 Aug 2026 | Added organization analytics endpoints to the dashboard interface to standardize contributor metric reporting[cite: 3]. |
| **Parameter Store Integration & Query Safeguards (`#173`)** | 1 Jun 2026 | Shifted database credential management to AWS Parameter Store inside `kpi_api_analytics.py` and applied stricter SQL filter bounds[cite: 3]. |
| **Metrics Decoupling & Resolution Tracking (`#169`)** | 18 May 2026 | Separated metric calculation routines and added validation checks on ticket resolution times to eliminate skewed analytical output[cite: 3]. |
| **Automated Categorization Service (`#100`, `#128`)** | 13 Apr 2026 | Implemented an OpenAI-backed classifier in `categorizer/` for incoming request processing, backed by a 10-case test suite[cite: 3]. |
| **Collaborator Evaluation Flags (`#113`)** | Mar 2026 | Introduced collaborator flagging logic across user and request analysis pipelines[cite: 3]. |
| **Isolated Landing Page Aggregation (`#103`)** | Mar 2026 | Deployed a dedicated Lambda function for homepage metrics to remove aggregation overhead from primary API handlers[cite: 3]. |
| **Schema Discovery & Mock Execution** | 13 Mar 2026 | Added `get_tables_info` in `utils/` alongside pandas-based synthetic data generators to enable full off-network local testing[cite: 3]. |
| **Scheduled Daily Aggregations (`#112`)** | 6 Mar 2026 | Built background aggregation tasks inside `aggregate-daily-metrics/` to pre-calculate daily performance stats for reporting tools[cite: 3]. |

---

### Architectural Evolution
Present system behavior is shaped by key historical refactorings designed to solve early performance and operational bottlenecks[cite: 2]:

| Evolutionary Shift | Technical Causality & System Impact |
| :--- | :--- |
| **Monolith Decomposition to Serverless** | Shifted core capabilities out of legacy `main.py` and `app.py` handlers into targeted Lambda packages (`saayam-org-aggregator`, `categorizer`), requiring automated injection of shared `utils/` during build steps[cite: 1, 2]. |
| **External AI Provider Integration** | Incorporated third-party inference models into `categorizer/`, necessitating vendor client libraries (`openai`) inside serverless deployment archives[cite: 3]. |
| **Centralized Credential Provisioning** | Replaced static configurations in `config.py` with runtime secret fetches from AWS Parameter Store across analytics handlers[cite: 3]. |
| **Resilient Relational Schema Introspection** | Standardized database reads through dynamic metadata tools (`get_tables_info`) to insulate API execution from upstream RDS table renames[cite: 1, 2, 3]. |
| **Development & Production Parity** | Standardized shared helper modules and introduced `python-dotenv` support to align local development environments with cloud runtime configurations[cite: 1, 3]. |