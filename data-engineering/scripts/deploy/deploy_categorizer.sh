#!/bin/bash
# Manual deploy script for the categorizer Lambda
# Usage: ./scripts/deploy/deploy_categorizer.sh

set -e

FUNCTION_NAME="auto-categorizer"
REGION="us-east-1"
SRC_DIR="src/categorizer"

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
