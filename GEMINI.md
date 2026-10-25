# Saayam Data Team Development Rules

This file documents critical guidelines and architectural constraints for development on the Saayam For All data repository. All AI assistants must adhere to these rules.

## Database Integration & Testing Guidelines

1. **No Live Database Connections in Development**
   * **Rule**: Never use AWS SSM Parameter Store credentials or connect directly to the live PostgreSQL database (`virginia_dev_saayam_rdbms` or `ireland_dev_saayam_rdbms`) during development.
   * **Reason**: Prevents exposing secrets, protects the production database from development workload, and guarantees network isolation.

2. **Use Mock CSV Files Only**
   * **Rule**: Always read and query data from mock CSV files located in `database/mock_db/` (such as `organizations.csv`, `state.csv`, `users.csv`).
   * **Implementation**: Emulate the database behavior in memory using a `sqlite3` database loaded with the CSV files. Map the CSV columns to target PostgreSQL tables and format types (e.g., date parsing, category mapping) dynamically.

3. **Provide Test Results Alongside DB-related Code Changes**
   * **Rule**: Whenever you modify or add database/analytics Lambda code, run the verification locally and generate/update a separate test results file named `<lambda_name>_test_results.txt` in the same directory.
   * **Reason**: Proves that the code has been successfully verified locally against all filters/events before the PR is submitted.
