#!/usr/bin/env bash
# ============================================================================
# Deploy the archival Lambda and its schedule.
#
# Creates no IAM, no bucket and no database objects. Uses the existing roles
# and bucket. The only statement the pipeline issues against an application
# table is SELECT.
#
# STATE_STORE decides where the watermark lives:
#
#   none      nothing persisted. Requires an explicit "from"/"to" in the
#             invocation payload, and cannot be scheduled. For testing before
#             the state tables exist.
#   postgres  archive_watermark / archive_run_log in the application schema.
#             Needs the two CREATE TABLEs run once by the DBA, plus
#             SELECT/INSERT/UPDATE on those two tables only.
#   s3        a JSON document in the archive bucket under _state/.
#             Needs s3:GetObject as well as PutObject.
#
# Switching between them is an environment variable, not a code change.
#
#   ./scripts/deploy/deploy_requests_archive.sh                      deploy or update
#   ./scripts/deploy/deploy_requests_archive.sh invoke               run once, using the configured store
#   ./scripts/deploy/deploy_requests_archive.sh range FROM TO        run once over an explicit range
#   ./scripts/deploy/deploy_requests_archive.sh logs                 tail the logs
#   ./scripts/deploy/deploy_requests_archive.sh teardown             remove the function and schedule
# ============================================================================
set -euo pipefail

REGION=${AWS_REGION:-us-east-1}
ACCT=$(aws sts get-caller-identity --query Account --output text)
DB_ID=${DB_ID:-saayam-dev-rds}
BUCKET=${BUCKET:-saayam-virginia-archive}
DB_PARAM=${DB_PARAM:-/dev/saayam/db/Virginia/Analytics/user}
FN=${FN:-saayam-archive-fn}
SCHED=${SCHED:-saayam-archive-schedule}
FN_ROLE_ARN=${FN_ROLE_ARN:-arn:aws:iam::${ACCT}:role/AWSDataPipelineDeployement-Role}
SCHED_ROLE_ARN=${SCHED_ROLE_ARN:-arn:aws:iam::${ACCT}:role/DataPipelineEventBridgeScheduler-role}
SCHEDULE=${SCHEDULE:-'cron(0 6 ? * MON *)'}
TZONE=${TZONE:-America/Phoenix}
RETENTION=${RETENTION:-90}
COMPRESS=${COMPRESS:-gzip}
STATE_STORE=${STATE_STORE:-none}
ARCHIVE_SCHEMA=${ARCHIVE_SCHEMA:-virginia_dev_saayam_rdbms}
HERE=$(cd "$(dirname "$0")/../.." && pwd)
SRC=$HERE/src/requests_archive
BUILD=/tmp/requests-archive-build

step(){ echo ""; echo "=============== $1"; }

case "${1:-deploy}" in
teardown)
  aws scheduler delete-schedule --name "$SCHED" --region "$REGION" 2>/dev/null \
    && echo "schedule deleted" || echo "no schedule"
  aws lambda delete-function --function-name "$FN" --region "$REGION" 2>/dev/null \
    && echo "function deleted" || echo "no function"
  echo "Log group and bucket left alone on purpose."
  exit 0;;
invoke)
  aws lambda invoke --function-name "$FN" --region "$REGION" \
    --cli-binary-format raw-in-base64-out \
    --payload '{"triggered_by":"manual"}' /tmp/out.json >/dev/null
  python3 -m json.tool /tmp/out.json 2>/dev/null || cat /tmp/out.json; echo; exit 0;;
range)
  [[ $# -eq 3 ]] || { echo "usage: ./scripts/deploy/deploy_requests_archive.sh range 'FROM' 'TO'"; exit 1; }
  aws lambda invoke --function-name "$FN" --region "$REGION" \
    --cli-binary-format raw-in-base64-out \
    --payload "{\"triggered_by\":\"manual\",\"from\":\"$2\",\"to\":\"$3\"}" /tmp/out.json >/dev/null
  python3 -m json.tool /tmp/out.json 2>/dev/null || cat /tmp/out.json; echo; exit 0;;
logs)
  aws logs tail "/aws/lambda/$FN" --follow --region "$REGION" --format short; exit 0;;
esac

case "$STATE_STORE" in none|postgres|s3) ;; *)
  echo "STATE_STORE must be none, postgres or s3. Got '$STATE_STORE'."; exit 1;; esac

step "1/5  checking the config parses before anything is deployed"
python3 -c "
import json,sys
d=json.load(open('$SRC/config.json'))
on=[t['name'] for t in d['tables'] if t.get('enabled',True)]
off=[t['name'] for t in d['tables'] if not t.get('enabled',True)]
print('     schema  :', d['schema'])
print('     enabled :', ', '.join(on) or 'none')
print('     disabled:', ', '.join(off) or 'none')
for t in d['tables']:
    if t.get('mode','incremental')=='incremental' and not t.get('timestamp_column'):
        sys.exit('     ERROR: %s is incremental with no timestamp_column' % t['name'])
inc=[t['name'] for t in d['tables'] if t.get('enabled',True)
     and t.get('mode','incremental')=='incremental']
if '$STATE_STORE'=='none' and inc:
    print('')
    print('     STATE_STORE=none: these tables are incremental and will only run')
    print('     with an explicit range -> ' + ', '.join(inc))
    print('     Use:  ./scripts/deploy/deploy_requests_archive.sh range \"2000-01-01 00:00:00\" \"<now, UTC>\"')
"

step "2/5  network details of the database"
# SG and SUBNETS can be passed in. Discovering them needs
# rds:DescribeDBInstances, which not every caller has.
if [[ -z "${SG:-}" || -z "${SUBNETS:-}" ]]; then
  if ! aws rds describe-db-instances --db-instance-identifier "$DB_ID" \
         --region "$REGION" >/dev/null 2>&1; then
    echo "     cannot read the RDS instance (rds:DescribeDBInstances)."
    echo "     Pass them instead:"
    echo "       SG=sg-xxxx SUBNETS=subnet-a,subnet-b STATE_STORE=$STATE_STORE ./scripts/deploy/deploy_requests_archive.sh"
    exit 1
  fi
  SG=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" --region "$REGION" \
        --query 'DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId' --output text)
  SUBNETS=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" --region "$REGION" \
        --query 'DBInstances[0].DBSubnetGroup.Subnets[].SubnetIdentifier' --output text | tr '\t' ',')
fi
echo "     security group $SG"
echo "     subnets        $SUBNETS"
echo ""
echo "     NOTE: the Lambda needs to reach the database on 5432. If the"
echo "     security group has no self-referencing rule, ask for one. I am not"
echo "     adding it here because that is a change to a shared group."

step "3/5  log group with retention"
# Neither call is required. Lambda creates its own log group on first
# invocation and retention only affects how long logs are kept, so a missing
# permission here is a warning, not a failure.
aws logs create-log-group --log-group-name "/aws/lambda/$FN" --region "$REGION" 2>/dev/null || true
if aws logs put-retention-policy --log-group-name "/aws/lambda/$FN" \
     --retention-in-days "$RETENTION" --region "$REGION" 2>/dev/null; then
  echo "     /aws/lambda/$FN, ${RETENTION} days"
else
  echo "     could not set retention (logs:PutRetentionPolicy). Continuing."
  echo "     Logs will be kept forever until someone sets it. Ask for"
  echo "     logs:PutRetentionPolicy when convenient, it is not urgent."
fi

step "4/5  building and deploying"
rm -rf "$BUILD"; mkdir -p "$BUILD"
pip install --quiet --target "$BUILD" pg8000 2>&1 | tail -1 || \
  pip3 install --quiet --target "$BUILD" pg8000
cp "$SRC/lambda_function.py" "$SRC/state.py" "$SRC/config.json" "$BUILD/"
( cd "$BUILD" && zip -qr /tmp/requests-archive-fn.zip . )
echo "     package $(du -h /tmp/requests-archive-fn.zip | cut -f1)"

# INLINE_DB_CREDS=1 reads the parameter here, where there is a route to SSM,
# and passes the value to the function as an environment variable. For a VPC
# with no SSM endpoint.
#
# EVALUATION ONLY. The password becomes readable by anyone who can call
# lambda:GetFunctionConfiguration, a much wider group than those who can
# decrypt the SecureString. Fix is an SSM interface endpoint or a NAT, then
# redeploy without this flag.
if [[ "${INLINE_DB_CREDS:-}" == "1" ]]; then
  echo ""
  echo "     !! INLINE_DB_CREDS=1: the database password will be stored as a"
  echo "     !! plaintext Lambda environment variable. Evaluation only."
  echo "     !! Redeploy without this flag once the VPC can reach SSM."
  echo ""
  DB_CONFIG_JSON=$(aws ssm get-parameter --name "$DB_PARAM" --with-decryption \
                     --region "$REGION" --query Parameter.Value --output text)
  [[ -n "$DB_CONFIG_JSON" ]] || { echo "could not read $DB_PARAM"; exit 1; }
  export DB_CONFIG_JSON
fi

# Built as a JSON file rather than the --environment shorthand: the shorthand
# splits on commas and equals signs, so it cannot carry a JSON value.
ENVFILE=/tmp/requests-archive-env.json
export BUCKET_V="$BUCKET" DB_PARAM_V="$DB_PARAM" COMPRESS_V="$COMPRESS" \
       STATE_STORE_V="$STATE_STORE" ARCHIVE_SCHEMA_V="$ARCHIVE_SCHEMA"
python3 - "$ENVFILE" <<'PY'
import json, os, sys
v = {
  "BUCKET":         os.environ["BUCKET_V"],
  "DB_PARAM":       os.environ["DB_PARAM_V"],
  "STREAM":         "main",
  "COMPRESS":       os.environ["COMPRESS_V"],
  "STATE_STORE":    os.environ["STATE_STORE_V"],
  "ARCHIVE_SCHEMA": os.environ["ARCHIVE_SCHEMA_V"],
}
for name in ("HASH_SALT_PARAM", "HASH_SALT", "DB_CONFIG_JSON", "S3_PREFIX"):
    if os.environ.get(name):
        v[name] = os.environ[name]
json.dump({"Variables": v}, open(sys.argv[1], "w"))
PY

if aws lambda get-function --function-name "$FN" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN" --region "$REGION" \
    --zip-file fileb:///tmp/requests-archive-fn.zip >/dev/null
  aws lambda wait function-updated --function-name "$FN" --region "$REGION"
  aws lambda update-function-configuration --function-name "$FN" --region "$REGION" \
    --environment "file://$ENVFILE" --timeout 900 --memory-size 512 >/dev/null
  aws lambda wait function-updated --function-name "$FN" --region "$REGION"
  echo "     updated"
else
  aws lambda create-function --function-name "$FN" --region "$REGION" \
    --runtime python3.12 --handler lambda_function.lambda_handler --role "$FN_ROLE_ARN" \
    --zip-file fileb:///tmp/requests-archive-fn.zip \
    --timeout 900 --memory-size 512 --ephemeral-storage Size=2048 \
    --vpc-config "SubnetIds=${SUBNETS},SecurityGroupIds=${SG}" \
    --environment "file://$ENVFILE" >/dev/null
  aws lambda wait function-active --function-name "$FN" --region "$REGION"
  echo "     created"
fi
rm -f "$ENVFILE"

# One run at a time. The SELECT ... FOR UPDATE on the watermark row (postgres)
# and the conditional write (s3) back this up.
aws lambda put-function-concurrency --function-name "$FN" \
  --reserved-concurrent-executions 1 --region "$REGION" >/dev/null
aws lambda put-function-event-invoke-config --function-name "$FN" \
  --maximum-retry-attempts 0 --region "$REGION" >/dev/null 2>&1 || true

step "5/5  schedule"
if [[ "$STATE_STORE" == "none" ]]; then
  aws scheduler delete-schedule --name "$SCHED" --region "$REGION" 2>/dev/null || true
  echo "     skipped. STATE_STORE=none has no watermark, so a scheduled run"
  echo "     would have no safe lower bound. Flip STATE_STORE to postgres or"
  echo "     s3 and redeploy to create the schedule."
else
  aws scheduler delete-schedule --name "$SCHED" --region "$REGION" 2>/dev/null || true
  aws scheduler create-schedule --name "$SCHED" --region "$REGION" \
    --schedule-expression "$SCHEDULE" --schedule-expression-timezone "$TZONE" \
    --flexible-time-window '{"Mode":"OFF"}' \
    --target "{\"Arn\":\"arn:aws:lambda:${REGION}:${ACCT}:function:${FN}\",
               \"RoleArn\":\"${SCHED_ROLE_ARN}\",
               \"Input\":\"{\\\"triggered_by\\\":\\\"eventbridge\\\"}\",
               \"RetryPolicy\":{\"MaximumRetryAttempts\":1}}" >/dev/null
  echo "     $SCHEDULE in $TZONE"
fi

cat <<EOF

--------------------------------------------------------------------------
Deployed with STATE_STORE=$STATE_STORE.

  ./scripts/deploy/deploy_requests_archive.sh range "2000-01-01 00:00:00" "$(date -u '+%Y-%m-%d %H:%M:%S')"
                         run once over an explicit range (works with any store)
  ./scripts/deploy/deploy_requests_archive.sh invoke     run once using the watermark (postgres / s3 only)
  ./scripts/deploy/deploy_requests_archive.sh logs       watch it

  aws s3 ls s3://$BUCKET/raw/ --recursive --human-readable

When the state tables exist:
  STATE_STORE=postgres ./scripts/deploy/deploy_requests_archive.sh
  SELECT * FROM $ARCHIVE_SCHEMA.archive_watermark;
  SELECT * FROM $ARCHIVE_SCHEMA.archive_run_log ORDER BY run_id DESC LIMIT 20;
--------------------------------------------------------------------------
EOF
