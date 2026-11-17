#!/usr/bin/env bash
# ============================================================================
# Deploy the requests backup export Lambda.
#
# Stage one of two. This one copies requests from Postgres to the backup
# bucket at full fidelity. Stage two reads that output and writes the
# de-identified copy to a different bucket.
#
# Creates no IAM, no bucket and no database objects. The only statement the
# pipeline issues against an application table is SELECT.
#
#   ./deploy_requests_backup.sh                 deploy or update
#   ./deploy_requests_backup.sh invoke          run once, using the watermark
#   ./deploy_requests_backup.sh range FROM TO   run once over an explicit range
#   ./deploy_requests_backup.sh logs            tail the logs
#   ./deploy_requests_backup.sh teardown        remove the function
# ============================================================================
set -euo pipefail

REGION=${AWS_REGION:-us-east-1}
ACCT=$(aws sts get-caller-identity --query Account --output text)
DB_ID=${DB_ID:-saayam-dev-rds}
BUCKET=${BUCKET:-saayam-virginia-archive}
DB_PARAM=${DB_PARAM:-/dev/saayam/db/Virginia/Analytics/user}
FN=${FN:-DE_ArchiveRequestsBackup}
FN_ROLE_ARN=${FN_ROLE_ARN:-arn:aws:iam::${ACCT}:role/AWSDataPipelineDeployement-Role}
STATE_STORE=${STATE_STORE:-postgres}
STREAM=${STREAM:-backup}
S3_PREFIX=${S3_PREFIX:-backup}
COMPRESS=${COMPRESS:-gzip}
ARCHIVE_SCHEMA=${ARCHIVE_SCHEMA:-virginia_dev_saayam_rdbms}
HERE=$(cd "$(dirname "$0")/../.." && pwd)
SRC=$HERE/src/requests_backup_export
BUILD=/tmp/requests-backup-build

step(){ echo ""; echo "=============== $1"; }

case "${1:-deploy}" in
teardown)
  aws lambda delete-function --function-name "$FN" --region "$REGION" 2>/dev/null \
    && echo "function deleted" || echo "no function"
  echo "Bucket and log group left alone on purpose."
  exit 0;;
invoke)
  aws lambda invoke --function-name "$FN" --region "$REGION" \
    --cli-binary-format raw-in-base64-out \
    --payload '{"triggered_by":"manual"}' /tmp/out.json >/dev/null
  python3 -m json.tool /tmp/out.json 2>/dev/null || cat /tmp/out.json; echo; exit 0;;
range)
  [[ $# -eq 3 ]] || { echo "usage: $0 range 'FROM' 'TO'"; exit 1; }
  aws lambda invoke --function-name "$FN" --region "$REGION" \
    --cli-binary-format raw-in-base64-out \
    --payload "{\"triggered_by\":\"manual\",\"from\":\"$2\",\"to\":\"$3\"}" /tmp/out.json >/dev/null
  python3 -m json.tool /tmp/out.json 2>/dev/null || cat /tmp/out.json; echo; exit 0;;
logs)
  aws logs tail "/aws/lambda/$FN" --follow --region "$REGION" --format short; exit 0;;
esac

step "1/4  checking the config parses"
python3 -c "
import json
d = json.load(open('$SRC/config.json'))
print('     schema :', d['schema'])
print('     table  :', d['table'])
print('     joins  :', ', '.join(j['table'] for j in d['joins']))
print('     geometry decoded:', ', '.join(d['geometry_columns']))
print('     not joined      :', ', '.join(d['expected_unjoined']))
"

step "2/4  network details of the database"
# SG and SUBNETS can be passed in. Discovering them needs
# rds:DescribeDBInstances, which not every caller has.
if [[ -z "${SG:-}" || -z "${SUBNETS:-}" ]]; then
  if ! aws rds describe-db-instances --db-instance-identifier "$DB_ID" \
         --region "$REGION" >/dev/null 2>&1; then
    echo "     cannot read the RDS instance. Pass them instead:"
    echo "       SG=sg-xxxx SUBNETS=subnet-a,subnet-b $0"
    exit 1
  fi
  SG=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" --region "$REGION" \
        --query 'DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId' --output text)
  SUBNETS=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" --region "$REGION" \
        --query 'DBInstances[0].DBSubnetGroup.Subnets[].SubnetIdentifier' --output text | tr '\t' ',')
fi
echo "     security group $SG"
echo "     subnets        $SUBNETS"

step "3/4  building and deploying"
rm -rf "$BUILD"; mkdir -p "$BUILD"
pip install --quiet --target "$BUILD" -r "$SRC/requirements.txt" 2>&1 | tail -1 || \
  pip3 install --quiet --target "$BUILD" -r "$SRC/requirements.txt"
cp "$SRC/lambda_function.py" "$SRC/state.py" "$SRC/config.json" "$BUILD/"
( cd "$BUILD" && zip -qr /tmp/requests-backup-fn.zip . )
echo "     package $(du -h /tmp/requests-backup-fn.zip | cut -f1)"

# INLINE_DB_CREDS=1 reads the parameter here, where there is a route to SSM,
# and passes the value in as an environment variable.
#
# EVALUATION ONLY. A Lambda environment variable is plaintext to anyone with
# lambda:GetFunctionConfiguration, a much wider group than can decrypt the
# SecureString. Remove once there is an SSM interface endpoint or a NAT.
if [[ "${INLINE_DB_CREDS:-}" == "1" ]]; then
  echo ""
  echo "     !! INLINE_DB_CREDS=1: the database password will be a plaintext"
  echo "     !! Lambda environment variable. Evaluation only."
  echo ""
  DB_CONFIG_JSON=$(aws ssm get-parameter --name "$DB_PARAM" --with-decryption \
                     --region "$REGION" --query Parameter.Value --output text)
  [[ -n "$DB_CONFIG_JSON" ]] || { echo "could not read $DB_PARAM"; exit 1; }
  export DB_CONFIG_JSON
fi

# Built as a JSON file rather than the --environment shorthand: the shorthand
# splits on commas and equals signs, so it cannot carry a JSON value.
ENVFILE=/tmp/requests-backup-env.json
export BUCKET_V="$BUCKET" DB_PARAM_V="$DB_PARAM" COMPRESS_V="$COMPRESS" \
       STATE_STORE_V="$STATE_STORE" ARCHIVE_SCHEMA_V="$ARCHIVE_SCHEMA" \
       STREAM_V="$STREAM" S3_PREFIX_V="$S3_PREFIX"
python3 - "$ENVFILE" <<'PY'
import json, os, sys
v = {k: os.environ[k + "_V"] for k in
     ("BUCKET","DB_PARAM","COMPRESS","STATE_STORE","ARCHIVE_SCHEMA","STREAM","S3_PREFIX")}
for name in ("DB_CONFIG_JSON",):
    if os.environ.get(name):
        v[name] = os.environ[name]
json.dump({"Variables": v}, open(sys.argv[1], "w"))
PY

if aws lambda get-function --function-name "$FN" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN" --region "$REGION" \
    --zip-file fileb:///tmp/requests-backup-fn.zip >/dev/null
  aws lambda wait function-updated --function-name "$FN" --region "$REGION"
  aws lambda update-function-configuration --function-name "$FN" --region "$REGION" \
    --environment "file://$ENVFILE" --timeout 900 --memory-size 512 >/dev/null
  aws lambda wait function-updated --function-name "$FN" --region "$REGION"
  echo "     updated"
else
  aws lambda create-function --function-name "$FN" --region "$REGION" \
    --runtime python3.12 --handler lambda_function.lambda_handler --role "$FN_ROLE_ARN" \
    --zip-file fileb:///tmp/requests-backup-fn.zip \
    --timeout 900 --memory-size 512 --ephemeral-storage Size=2048 \
    --vpc-config "SubnetIds=${SUBNETS},SecurityGroupIds=${SG}" \
    --environment "file://$ENVFILE" >/dev/null
  aws lambda wait function-active --function-name "$FN" --region "$REGION"
  echo "     created"
fi
rm -f "$ENVFILE"

# One run at a time. The SELECT ... FOR UPDATE on the watermark row backs
# this up.
aws lambda put-function-concurrency --function-name "$FN" \
  --reserved-concurrent-executions 1 --region "$REGION" >/dev/null
aws lambda put-function-event-invoke-config --function-name "$FN" \
  --maximum-retry-attempts 0 --region "$REGION" >/dev/null 2>&1 || true

step "4/4  done"
cat <<EOF
  $0 range "2000-01-01 00:00:00" "$(date -u '+%Y-%m-%d %H:%M:%S')"
  $0 invoke
  $0 logs

  aws s3 ls s3://$BUCKET/$S3_PREFIX/ --recursive --human-readable

  SELECT * FROM $ARCHIVE_SCHEMA.archive_watermark WHERE stream = '$STREAM';
  SELECT * FROM $ARCHIVE_SCHEMA.archive_run_log ORDER BY run_id DESC LIMIT 10;
EOF
