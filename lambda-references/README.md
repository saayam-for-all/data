# Repository-first Lambda audit snapshot - issue #593

This document records the initial pre-AWS repository audit. Later PRs #613 and #615 added two Data Engineering workloads. For the current counts, deployed names, and verified console links, see [AWS_RECONCILIATION.md](AWS_RECONCILIATION.md).

Repository-first audit on 2026-10-27. Sources: the `main`, `dev`, and `test` branches of `saayam-for-all/data`; all 18 issues labeled `data engineering`; all 17 labeled `Data Analysis`; and 45 Lambda-related issue search results (53 distinct issues in the union). Open PRs are separated from merged branch references.

**Provisional GitHub workload count: 4 Data Engineering; 12 Data Analytics.** This is not a confirmed count of deployed AWS Lambda functions. A workload can have multiple proposed filenames or PRs, while a repository file alone does not prove deployment. Exact AWS names, account/region, active status, and console links require read-only Lambda access. No console URL is guessed.

| Team | Workload / proposed name | Task evidence | Repository reference | AWS console link |
| --- | --- | --- | --- | --- |
| Engineering | Organization aggregator (`saayam-org-aggregator`) | [#98](https://github.com/saayam-for-all/data/issues/98), [#113](https://github.com/saayam-for-all/data/issues/113), [#433](https://github.com/saayam-for-all/data/issues/433) | [dev source](https://github.com/saayam-for-all/data/tree/dev/data-engineering/src/saayam-org-aggregator); [deploy script](https://github.com/saayam-for-all/data/blob/dev/data-engineering/scripts/deploy/deploy_aggregator.sh) says `org-aggregator`, so confirm AWS name | Pending |
| Engineering | Help-request categorizer (`auto-categorizer` in script) | [#100](https://github.com/saayam-for-all/data/issues/100) | [dev handler](https://github.com/saayam-for-all/data/blob/dev/data-engineering/src/categorizer/handler.py), [deploy script](https://github.com/saayam-for-all/data/blob/dev/data-engineering/scripts/deploy/deploy_categorizer.sh) | Pending |
| Engineering | Daily homepage metrics (AWS name unconfirmed) | [#103](https://github.com/saayam-for-all/data/issues/103) | [dev handler](https://github.com/saayam-for-all/data/blob/dev/data-engineering/src/aggregate-daily-metrics/lambda_function.py) | Pending |
| Engineering | Request archive (`Data_ArchiveRequestData`, proposed) | [#574](https://github.com/saayam-for-all/data/issues/574), [#582](https://github.com/saayam-for-all/data/issues/582) | [Open PR #584](https://github.com/saayam-for-all/data/pull/584), not merged into checked branches | Pending |
| Analytics | Beneficiary trend (`beneficiary_trend_analysis.py` in task) | [#138](https://github.com/saayam-for-all/data/issues/138) | [main source](https://github.com/saayam-for-all/data/blob/main/data-analytics/lambda_functions/beneficiariesTrendAnalysis.py); filename differs from task | Pending |
| Analytics | Request application analytics | [#146](https://github.com/saayam-for-all/data/issues/146) | [Open PR #167](https://github.com/saayam-for-all/data/pull/167), not merged | Pending |
| Analytics | Volunteer application analytics | [#151](https://github.com/saayam-for-all/data/issues/151), [#179](https://github.com/saayam-for-all/data/issues/179) | [dev source](https://github.com/saayam-for-all/data/blob/dev/data-analytics/lambda_functions/volunteer_application_analytics.py) | Pending |
| Analytics | Super Admin KPI analytics | [#160](https://github.com/saayam-for-all/data/issues/160), [#181](https://github.com/saayam-for-all/data/issues/181) | [dev source](https://github.com/saayam-for-all/data/blob/dev/data-analytics/lambda_functions/kpi_api_analytics.py) | Pending |
| Analytics | Steward volunteer review | [#273](https://github.com/saayam-for-all/data/issues/273) | [Open PR #374](https://github.com/saayam-for-all/data/pull/374), not merged | Pending |
| Analytics | Organization dashboard overview | [#228](https://github.com/saayam-for-all/data/issues/228) | [Open PR #257](https://github.com/saayam-for-all/data/pull/257) and alternatives, not merged | Pending |
| Analytics | Organization growth/location | [#336](https://github.com/saayam-for-all/data/issues/336), [#539](https://github.com/saayam-for-all/data/issues/539) | [test source](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/growth_trend_analytics.py); competing PRs propose other names | Pending |
| Analytics | Organization size/contribution | [#376](https://github.com/saayam-for-all/data/issues/376), [#569](https://github.com/saayam-for-all/data/issues/569), [#583](https://github.com/saayam-for-all/data/issues/583) | [test source](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/size_and_contribution.py); #583 proposes another filename for the same API | Pending |
| Analytics | Organization rating/type | [#380](https://github.com/saayam-for-all/data/issues/380), [#506](https://github.com/saayam-for-all/data/issues/506) | [test source](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/rating_type_analytics.py) | Pending |
| Analytics | Additional request details | [#203](https://github.com/saayam-for-all/data/issues/203) | [Open PR #214](https://github.com/saayam-for-all/data/pull/214), not merged | Pending |
| Analytics | Available-volunteer lookup | [#289](https://github.com/saayam-for-all/data/issues/289) | [Open PR #358](https://github.com/saayam-for-all/data/pull/358); alternative names exist | Pending |
| Analytics | Assigned-volunteer lookup | [#295](https://github.com/saayam-for-all/data/issues/295) | [Open PR #342](https://github.com/saayam-for-all/data/pull/342), not merged | Pending |

## Unresolved ownership and historical candidates

- [#60](https://github.com/saayam-for-all/data/issues/60) proposes an IRS-to-S3 Lambda, but the [Engineering tracker](https://github.com/saayam-for-all/data/blob/dev/data-engineering/TASK_TRACKER.md) says IRS data was later dropped. Check whether an old function remains in AWS.
- [#334](https://github.com/saayam-for-all/data/issues/334) and [#482](https://github.com/saayam-for-all/data/issues/482) mention an Emergency Contacts Lambda without an exact name or confirmed team owner.
- [#92](https://github.com/saayam-for-all/data/issues/92) describes a Data ML Lambda. [#98](https://github.com/saayam-for-all/data/issues/98) names `More_Org_GenAI_Py_v3126` as an **AI-team dependency**. Confirm ownership before counting either.
- [#422](https://github.com/saayam-for-all/data/issues/422) mentions a Profanity API; [PR #559](https://github.com/saayam-for-all/data/pull/559) proposes a content-filter Lambda. Confirm ownership and deployment.
- [#416](https://github.com/saayam-for-all/data/issues/416) explicitly specifies **no Lambda** for its original archive design; the replacement Lambda in #574 is tracked separately.

## AWS reconciliation

Once read-only access is granted, list Lambda functions in the relevant Saayam accounts and regions. Verify exact name, owning team, deployment state, handler/repository path, and direct console link for every row. Merge aliases only after AWS confirms they are the same function. Add AWS-only functions missed by the issue search and correct the team totals. Do not commit credentials, environment values, or private configuration to this public repository.
