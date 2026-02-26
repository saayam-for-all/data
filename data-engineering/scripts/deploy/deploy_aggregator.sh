#!/bin/bash
# Manual deploy script for the aggregator Lambda
# Usage: ./scripts/deploy/deploy_aggregator.sh
# Future: wire this into GitHub Actions on merge to main

set -e

FUNCTION_NAME="org-aggregator"
REGION="us-east-1"
SRC_DIR="src/aggregator"

echo "Packaging $FUNCTION_NAME..."
cd $SRC_DIR
zip -r ../../dist/${FUNCTION_NAME}.zip .
cd ../..

echo "Deploying to AWS Lambda..."
aws lambda update-function-code \
  --function-name $FUNCTION_NAME \
  --zip-file fileb://dist/${FUNCTION_NAME}.zip \
  --region $REGION

echo "Done. $FUNCTION_NAME deployed."
