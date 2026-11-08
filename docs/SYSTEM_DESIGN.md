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

# §2 Architecture & System Placement

Data Engineering & Analytics enriches reporting and insights infrastructure. It does not own transactional core lifecycles; request microservices own transaction flows, while data pipelines consume, aggregate, and analyze generated telemetry.

### Core Architectural Layers

- **Callers & Upstream Services:**
  - Front-end analytics consumers, reporting dashboards, and internal microservice event triggers (such as `saayam-org-aggregator`).
  - FastAPI application entry point (`data-engineering/src/main.py`) exposing core analytics and data endpoints.

- **Compute (Serverless Lambda & Handlers):**
  - **Analytics Handlers (`data-analytics/lambda_functions/` & `data-engineering/src/`):**
    - `kpi_api_analytics.py` (Core KPI reporting)
    - `beneficiariesTrendAnalysis.py` (Multi-region trend evaluations)
    - `volunteer_application_analytics.py` (Volunteer metrics processing)
    - `organization_size_contribution_api.py` (Organization contribution sizing)
  - **Background & Aggregation Handlers:**
    - `aggregate-daily-metrics/lambda_function.py` (Scheduled metric rollups)
    - `saayam-org-aggregator/lambda_function.py` (Org-level metric synchronization)
    - `categorizer/handler.py` (LLM-based categorization pipelines)

- **Configuration & Secrets Management:**
  - Secrets and database configurations are dynamically fetched at runtime from AWS SSM Parameter Store (`us-east-1` region).
  - Parameter paths follow hierarchical structures (e.g., `/dev/saayam/db/Virginia/Analytics/user` and `/dev/saayam/db/Ireland/Analytics/user`).

- **Data Stores & Persistence:**
  - Dual-region PostgreSQL database architecture supporting Virginia and Ireland instances.
  - Connections managed via `psycopg2` (with `RealDictCursor` for structured payload mapping) and `pg8000`.

### Critical Path vs. Non-Critical Execution

- **Real-time Analytics Queries (Critical Path):**
  - Endpoints relying on live execution (e.g., FastAPI routes in `main.py` and real-time KPI aggregations) directly query the database connection pools (`get_db_connection()`). Failures in database connectivity raise explicit 500-level HTTP exceptions or caught operational errors.

- **Background Metric Aggregations (Non-Critical / Asynchronous):**
  - Daily metric rollups and aggregator routines operate off the immediate user request path, executing via scheduled events or background triggers to pre-compute analytics data caches.

---

# §3 Data Ingestion, Scraping & Pipeline Workflows

The data engineering ecosystem relies on modular extraction pipelines, region-specific web scrapers, daily aggregation tasks, and multilingual text processing utilities to feed and maintain downstream analytical stores.

### 3.1 Regional NGO Scrapers (`data-engineering/src/scrapers/ngo/`)

- **Purpose:** Automated extraction of regional partner and NGO datasets to populate local organizational directories.
- **Modules:**
  - `india.py`: India-specific NGO directory extraction routines.
  - `afghanistan.py`: Afghanistan regional entity harvesting.
  - `malaysia.py`: Malaysia-specific partner data collection.

### 3.2 Emergency Contacts ETL Pipeline (`data-engineering/src/scrapers/emergency_contacts/`)

- **Purpose:** Structured ingestion pipeline dedicated to gathering, sanitizing, and loading critical emergency contact databases.
- **Architecture Stages:**
  - `scraper.py`: Extracts raw emergency contact records from target sources.
  - `cleaner.py`: Standardizes fields, strips invalid tokens, and normalizes phone numbers/metadata.
  - `loader.py`: Handles batch writes and target persistence into operational databases.

### 3.3 Daily Metrics Aggregation (`data-engineering/src/aggregate-daily-metrics/`)

- **Purpose:** Scheduled background tasks that pre-compute performance rollups, minimizing query overhead for user-facing analytics tools.
- **Components:**
  - `lambda_function.py`: Entry point for scheduled metric generation.
  - `helpers.py`: Supporting utility functions handling data transformation and persistence logic.

### 3.4 Multilingual Text Processing & Translation (`data-engineering/src/translation/`)

- **Purpose:** Provides localization support and language identification for incoming data payloads and requests.
- **Components:**
  - `lang_detection.py`: Handles automatic detection of source languages to ensure correct downstream routing and categorization.

---

# §4 Classification & Categorization Service

The classification subsystem handles incoming user requests to automatically categorize text descriptions into structured organizational taxonomy paths. Located within `data-engineering/src/categorizer/`, the service is structured for modular execution, fault isolation, and graceful degradation.

### 4.1 Module Structure & Components

The categorization package comprises core taxonomy definitions, classification logic, and serverless handler wrappers:

- `categories.py`: Houses the master taxonomy definition containing 717 total entries, predominantly representing form fields, sub-options, and categorical classifications (such as "Social Connection").
- `classifier.py`: Implements the core traversal and classification strategy.
- `handler.py`: Serves as the AWS Lambda entry point (`lambda_handler`), managing event parsing and execution responses.

### 4.2 Request Parsing & Execution Flow (`handler.py`)

The serverless handler processes incoming events flexibly to accommodate variations across API Gateway integrations:

- **Payload Normalization:** Inspects the event payload, checking if `body` is a JSON-encoded string or a direct dictionary object, and safely extracts subject and description strings.
- **Classification Trigger:** Invokes `classify_request(subject, description)` to evaluate the input against the taxonomy tree.
- **Response Envelope:** On successful evaluation, returns a 200 status code with the classification payload.

### 4.3 Taxonomy Strategy & Recursive Descent

The system utilizes a recursive descent classification strategy across the 717-entry taxonomy space. Rather than evaluating all nodes in a single flat pass, the classifier traverses the categorical hierarchy iteratively or recursively to match user intents with appropriate subcategories.

### 4.4 Error Handling & Fail-Safe Behavior

To prevent background or inline classification failures from blocking core user request workflows, the handler implements strict exception catching:

- **Fail-Safe Fallback:** If an unhandled exception or operational error occurs during execution, the handler catches the exception and returns a structured response defaulting the category and subcategory to "General" with a confidence score of `0.0`.
- **Unblocked Pipelines:** This ensures that upstream user-facing applications never experience hard request failures due to transient classification errors or parsing anomalies.

---

# §5 Analytics & Aggregation Services

### 5.1 Organization Aggregation & Parallel Execution (`saayam-org-aggregator/`)

The organization aggregator Lambda function (`lambda_function.py`) unifies database-backed entities with dynamic generative outputs to surface relevant non-profits and community resources:

- **Input Validation & Payload Handling:** Normalizes incoming event payloads and strictly validates that both location and category are provided as required fields; missing parameters trigger a 400 Bad Request response.
- **Concurrent Execution:** Utilizes Python's `ThreadPoolExecutor` to invoke database lookups (`get_orgs_from_db`) and AI-driven provider queries (`get_ai_orgs`) in parallel, minimizing latency for user-facing applications.
- **Result Merging:** Passes the concurrent futures into `merge_organizations()` to deduplicate and format the combined enterprise roster before returning a standard HTTP 200 response package.

### 5.2 KPI Analytics & Reporting Engine (`kpi_api_analytics.py`)

The KPI analytics module drives metrics computation and operational reporting against the multi-region PostgreSQL environment:

- **Credential Management:** Securely retrieves database credentials at runtime using AWS Lambda Powertools parameter stores (targeting paths such as `/dev/saayam/db/Virginia/Analytics/user`).

- **Database Connectivity & Lifecycle:** Establishes secure connections to the primary schema (`virginia_dev_saayam_rdbms`) utilizing `psycopg2` with `RealDictCursor` factories for dictionary-mapped row processing, managed via explicit `try/except/finally` blocks to guarantee cursor and connection cleanup.

- **SLA Framework:** Enforces standardized Service Level Agreement (SLA) parameters across reporting endpoints:
  - **Target Resolution:** 10 days (240 hours)
  - **Warning Threshold:** 8.33 days (200 hours)

- **Isolated Metric Queries & Granular Fault Tolerance:** The handler computes executive metrics through three isolated database functions (`fetch_request_status_distribution`, `fetch_total_requests`, and `fetch_average_resolution_time_by_category`). Each query fetch is wrapped in its own exception handler—if an individual sub-query fails, it logs the error and gracefully falls back to empty or zeroed default values (`[]` or `0`) rather than crashing the entire metrics payload.

- **Default Response Structure:** Yields standardized metrics payloads containing request status distributions, total volume tracking, category-specific average resolution times, and embedded SLA thresholds.

---

# §6 Database Access, Utilities & Application Core

The foundational layer supporting core routing, fraud detection, and transactional data models consists of modular utility scripts, SQLAlchemy configurations, and application bootstrapping files. This architecture establishes a clean separation of concerns between web entry points, state persistence, and helper business logic.

### 6.1 Application Bootstrapping & Core Routing (`app.py`)

The primary Flask application bootstrap initializes the web service execution context, manages ORM bindings, and exposes core API routes:

- **Dynamic Configuration & ORM Initialization:** The application loads configuration properties dynamically via `app.config.from_object(config)` and binds database management through Flask-SQLAlchemy (`db.init_app(app)`).

- **Automatic Schema Provisioning:** On application startup, an explicit application context (`with app.app_context(): db.create_all()`) inspects active models and provisions missing tables, streamlining local development and containerized deployments.

- **Health Check & Diagnostic Endpoints:** Exposes a lightweight root status check (`/`) returning "Service is running" to verify container responsiveness and load balancer health.

- **Fraud Detection & Sliding-Window Analysis (`/api/check_fraud`):** Implements transaction monitoring by parsing incoming JSON payloads, extracting user identifiers and timestamps, and converting string datetimes into Python datetime objects. The endpoint computes a sliding 30-minute historical window (`time_window_start = request_datetime - timedelta(minutes=30)`) to evaluate concurrent or rapid-fire submission behaviors against historical records.

### 6.2 Configuration Management & Database Connectivity (`config.py`)

The configuration module decouples environment-specific parameters from business logic:

- **Database URI Specification:** Establishes connection parameters targeting containerized or local PostgreSQL instances (`SQLALCHEMY_DATABASE_URI = 'postgresql://postgres:[password@host.docker.internal](mailto:password@host.docker.internal):5432/Saayam'`).

- **Memory & Performance Tuning:** Explicitly disables SQLAlchemy object modification tracking (`SQLALCHEMY_TRACK_MODIFICATIONS = False`) to eliminate unnecessary memory overhead and signal emission during high-frequency request processing.

### 6.3 Introspection & Temporal Utility Modules (`utils/`)

The utility package provides specialized helper functions to support database auditing and temporal analytics:

- **Schema & Table Inspection (`get_tables_info.py`):** Supplies lightweight metadata introspection helpers that programmatically query database schemas, allowing backend services and diagnostic scripts to inspect table structures, column definitions, and relational states without manual SQL intervention.

- **Temporal Filtering & Windowing (`time_filters.py`):** Encapsulates datetime manipulation, zone normalization, and window delta calculations. Working in tandem with fraud detection and reporting routes, these utilities ensure that time-sensitive metrics and sliding-window queries execute with precise temporal boundaries.

---

# §7 Deployment Architecture, Infrastructure & Operational Monitoring

The deployment and operational architecture for the `saayam-for-all/data` repository is designed around a serverless, multi-region cloud model. This ensures high availability, strict credential security, and fault isolation across concurrent workloads.

### 7.1 Serverless & Compute Infrastructure

The compute layer relies heavily on AWS Lambda serverless functions to execute event-driven tasks without idle infrastructure overhead:

- **Asynchronous & Scheduled Tasks:** Scraping pipelines, organization aggregators, and the 717-entry taxonomy classifier operate within dedicated Lambda execution environments.
- **Concurrency & Parallelism:** Services like the organization aggregator leverage Python's `ThreadPoolExecutor` within Lambda handlers to execute concurrent network and database calls (e.g., simultaneous database queries and GenAI provider lookups) while respecting execution timeout windows.
- **Containerized & Flask App Runtimes:** Companion backend components (such as the fraud detection and routing services) are packaged for containerized deployment, utilizing Flask with SQLAlchemy connection pooling configured via environment parameters.

### 7.2 Secrets & Configuration Management (AWS SSM)

To maintain security compliance and eliminate hardcoded credentials across source code repositories:

- **Runtime Parameter Resolution:** Database credentials, API keys, and environment-specific endpoints are retrieved dynamically at runtime using AWS Systems Manager (SSM) Parameter Store or AWS Lambda Powertools utilities.
- **Regional Isolation:** Parameter paths are strictly segregated by geographic and deployment scope (e.g., `/dev/saayam/db/Virginia/Analytics/user`), ensuring that Virginia and Ireland instances pull precise, least-privilege configurations without cross-environment leakage.

### 7.3 Multi-Region Data Topologies

The database tier utilizes a multi-region PostgreSQL architecture spanning primary clusters in Virginia and Ireland:

- **Geographic Proportionality:** Regional workloads route queries to their respective local database instances to minimize cross-region network latency.
- **Resilient Connection Handling:** Application database connectors utilize robust connection lifecycles (explicit `try/except/finally` blocks with `psycopg2` and `RealDictCursor`) ensuring that idle connections are purged and cursors are safely closed to prevent connection pool exhaustion.

### 7.4 Logging, Observability & Fail-Safe Patterns

To guarantee system stability under heavy user traffic or transient third-party failures, the architecture implements defensive error boundaries:

- **Granular Sub-Query Isolation:** Analytical and aggregation endpoints isolate individual metric fetches (e.g., status distributions, total counts, resolution times). If a single sub-query or external dependency fails, it is caught locally, logged to CloudWatch, and assigned a safe default (`[]` or `0`) rather than triggering a 500 server crash.
- **Graceful Degradation:** Higher-level classification and aggregation components default to fallback states (such as categorizing unparseable or failed requests as "General" with `0.0` confidence), ensuring that core user-facing application flows remain unblocked.