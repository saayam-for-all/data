# Lambda Function Inventory — Issue #593

## Method

I reviewed the Data Engineering and Data Analytics labeled tasks and the Lambda-related issues,
walked the `main`, `dev`, and `test` branches of this repository for Lambda handlers and deploy
definitions, and then checked the AWS console (read-only, account `revanth-saayam`) for the deployed
functions. Deploys go through the GitHub Actions workflow (`.github/workflows/deploy-lambda.yml`),
which takes the function name as an input, so the older `deploy_*.sh` scripts can carry out-of-date
names. Deployed code was compared by name, purpose, and package details; where a side-by-side code
comparison against the deployed function was not possible, the row is marked unconfirmed rather than
guessed.

**Regions:** us-east-1 reviewed in full — 216 functions at the time of review. us-east-2 reviewed —
3 functions (`updateVolunteer`, `volunteer-crud-saayam`, `Saayam-AppConfig`), all volunteer CRUD /
app config, none belonging to these teams. Other regions were not part of this review.

## Totals

| Team | Task workloads reviewed | Merged repo code | Open PR only | Confirmed deployed |
|---|---:|---:|---:|---:|
| Data Engineering | 8 | 5 | 3 | 3 |
| Data Analytics | 12 | 6 | 6 | 5 |

Confirmed deployed — Data Engineering: `saayam-org-aggregator`, `aggregate-daily-metrics`, `saayam-archive-fn`.
Confirmed deployed — Data Analytics: `beneficiariesTrendAnalysis`, `volunteerApplicationAnalytics`, `requestApplicationAnalytics`, `growth_trend_analytics`, `rating_type_analytics`.
Shared/unconfirmed: `kpiAnalytics` (two divergent repo copies — engineering single-period, analytics multi-period; owner to confirm) and the help-request categorizer alias.

## Data Engineering

| Workload | Lambda Function Name | Reference in Repo | Repository Reference Link | AWS Lambda Link | Notes |
|---|---|---|---|---|---|
| Organization aggregator | saayam-org-aggregator | Yes | [data-engineering/src/saayam-org-aggregator/lambda_function.py](https://github.com/saayam-for-all/data/blob/test/data-engineering/src/saayam-org-aggregator/lambda_function.py) | [saayam-org-aggregator](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/saayam-org-aggregator) | Exact name match. `deploy_aggregator.sh` says `org-aggregator`; deploys go through the GitHub Actions workflow, so the script name is out of date. |
| Help-request categorizer | predict_category (unconfirmed) | Yes | [data-engineering/src/categorizer/handler.py](https://github.com/saayam-for-all/data/blob/test/data-engineering/src/categorizer/handler.py) | [predict_category](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/predict_category) | `deploy_categorizer.sh` expects `auto-categorizer`, which is not deployed. `predict_category` matches the purpose but its handler entry point differs from the repo file; alias unconfirmed. |
| Daily homepage metrics | aggregate-daily-metrics | Yes | [data-engineering/src/aggregate-daily-metrics/lambda_function.py](https://github.com/saayam-for-all/data/blob/test/data-engineering/src/aggregate-daily-metrics/lambda_function.py) | [aggregate-daily-metrics](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/aggregate-daily-metrics) | Exact name match. `statsForHomepage` also deployed — see no-reference list. |
| Super Admin KPI analytics (engineering copy) | kpiAnalytics (unconfirmed) | Yes | [data-engineering/src/kpi_api_analytics.py](https://github.com/saayam-for-all/data/blob/test/data-engineering/src/kpi_api_analytics.py) | [kpiAnalytics](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/kpiAnalytics) | Engineering and analytics copies are divergent versions (single-period vs 7D/30D/1Y/All/Custom); which copy is deployed was not confirmed. |
| Organization size & contribution (engineering copy) | — | Yes (test branch only) | [data-engineering/src/organization_size_contribution_analytics/lambda_function.py](https://github.com/saayam-for-all/data/blob/test/data-engineering/src/organization_size_contribution_analytics/lambda_function.py) | — | Not deployed under the repo name; overlaps Data Analytics #376. |
| Request archival (#416) | saayam-archive-fn | No — open [#615](https://github.com/saayam-for-all/data/pull/615) only | [#615](https://github.com/saayam-for-all/data/pull/615) | [saayam-archive-fn](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/saayam-archive-fn) | Deployed name matches the PR's deploy script; PR #615 reports it verified against the dev database. |
| Content filter / profanity check (#422) | checkProfanity (possible) | No — open [#613](https://github.com/saayam-for-all/data/pull/613) only | [#613](https://github.com/saayam-for-all/data/pull/613) | [checkProfanity](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/checkProfanity) | PR #613 states nothing from it is deployed yet; `checkProfanity`/`testCheckProfanity` may be older implementations. |
| Request archive replacement (#574/#582) | — | No — open [#584](https://github.com/saayam-for-all/data/pull/584) only | [#584](https://github.com/saayam-for-all/data/pull/584) | — | Proposed `Data_ArchiveRequestData` not deployed; deployed `saayam-archive-fn` belongs to #416. |

## Data Analytics

| Workload | Lambda Function Name | Reference in Repo | Repository Reference Link | AWS Lambda Link | Notes |
|---|---|---|---|---|---|
| Beneficiary trend analysis | beneficiariesTrendAnalysis | Yes | [data-analytics/lambda_functions/beneficiariesTrendAnalysis.py](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/beneficiariesTrendAnalysis.py) | [beneficiariesTrendAnalysis](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/beneficiariesTrendAnalysis) | Exact name match. |
| Volunteer application analytics | volunteerApplicationAnalytics | Yes | [data-analytics/lambda_functions/volunteer_application_analytics.py](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/volunteer_application_analytics.py) | [volunteerApplicationAnalytics](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/volunteerApplicationAnalytics) | Queries volunteer tables and returns volunteer trends; clearly this function. `requestApplicationAnalytics` is a separate request-data function (#146). |
| Super Admin KPI analytics (analytics copy) | kpiAnalytics (unconfirmed) | Yes | [data-analytics/lambda_functions/kpi_api_analytics.py](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/kpi_api_analytics.py) | [kpiAnalytics](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/kpiAnalytics) | Same deployed function as the engineering row; owner to confirm. |
| Organization growth / location trend | growth_trend_analytics | Yes (test branch only) | [data-analytics/lambda_functions/growth_trend_analytics.py](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/growth_trend_analytics.py) | [growth_trend_analytics](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/growth_trend_analytics) | Exact name match (#336/#539). |
| Organization rating & type | rating_type_analytics | Yes (test branch only) | [data-analytics/lambda_functions/rating_type_analytics.py](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/rating_type_analytics.py) | [rating_type_analytics](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/rating_type_analytics) | Exact name match (#380/#506). |
| Organization size & contribution | — | Yes (test branch only) | [data-analytics/lambda_functions/size_and_contribution.py](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/size_and_contribution.py) | — | Not deployed under the repo name (#376); overlaps the engineering copy. |
| Request application analytics (#146) | requestApplicationAnalytics | No — open [#167](https://github.com/saayam-for-all/data/pull/167) only | [#167](https://github.com/saayam-for-all/data/pull/167) | [requestApplicationAnalytics](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/requestApplicationAnalytics) | Deployed and matches name/purpose; repo reference is an open PR. |
| Steward volunteer review (#273) | — | No — open [#374](https://github.com/saayam-for-all/data/pull/374) only | [#374](https://github.com/saayam-for-all/data/pull/374) | — | No unambiguous deployed match. |
| Organization dashboard overview (#228) | — | No — open [#257](https://github.com/saayam-for-all/data/pull/257) only | [#257](https://github.com/saayam-for-all/data/pull/257) | — | Several generic organization functions exist; none unambiguous. |
| Additional request details (#203) | getAdditionalInfo (possible) | No — open [#214](https://github.com/saayam-for-all/data/pull/214) only | [#214](https://github.com/saayam-for-all/data/pull/214) | [getAdditionalInfo](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/getAdditionalInfo) | Alias not verified. |
| Available-volunteer lookup (#289) | fetchVolunteersBasedOnSkills (possible) | No — open [#358](https://github.com/saayam-for-all/data/pull/358) only | [#358](https://github.com/saayam-for-all/data/pull/358) | [fetchVolunteersBasedOnSkills](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/fetchVolunteersBasedOnSkills) | Alias and matching rules not verified. |
| Assigned-volunteer lookup (#295) | getVolunteers (possible) | No — open [#342](https://github.com/saayam-for-all/data/pull/342) only | [#342](https://github.com/saayam-for-all/data/pull/342) | [getVolunteers](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/getVolunteers) | Generic name; alias not verified. |

## Deployed functions with no repository reference

| Lambda Function Name | AWS Lambda Link | Notes |
|---|---|---|
| statsForHomepage | [statsForHomepage](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/statsForHomepage) | Homepage statistics; may be an older implementation of the daily homepage metrics workload (#103). |
| irsDataCategorizer | [irsDataCategorizer](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/irsDataCategorizer) | IRS categorization; the engineering TASK_TRACKER notes IRS data work was dropped. |
| irs_data_subcategorization | [irs_data_subcategorization](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/irs_data_subcategorization) | IRS sub-categorization; same note. |
| upload-irs-data-to-s3 | [upload-irs-data-to-s3](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/upload-irs-data-to-s3) | Matches historical task #60; excluded from team totals pending owner confirmation. |

## Open items for a team owner

1. Which deployed function serves the help-request categorizer (`predict_category` vs the IRS categorizers)?
2. Which team owns `kpiAnalytics`, given the two divergent repo copies?
3. Is `size_and_contribution` / `organization_size_contribution_analytics` deployed under a different name?
4. Owners for the four no-reference functions listed above.

The Excel version of this inventory is committed alongside: `Lambda_Function_Inventory_593_SnehalShan.xlsx`.
