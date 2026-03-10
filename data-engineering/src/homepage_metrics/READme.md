# Homepage Metrics Aggregation Lambda

## Overview
This Lambda function runs daily (triggered by EventBridge) and aggregates four key homepage metrics from the Saayam Aurora/Postgres database. The results are written to an S3 bucket as a JSON file for the frontend to consume.

## Metrics Computed
- totalRequests
- requestsResolved
- totalVolunteers
- totalBeneficiaries

## JSON Output Schema
{
  "totalRequests": number,
  "requestsResolved": number,
  "totalVolunteers": number,
  "totalBeneficiaries": number
}

## S3 Output
Bucket: saayam-public-metrics  
Key: homepage/metrics.json  

## SQL Queries
SELECT COUNT(*) FROM requests;
SELECT COUNT(*) FROM requests WHERE status = 'resolved';
SELECT COUNT(*) FROM volunteers;
SELECT COUNT(*) FROM beneficiaries;

## Environment Variables (set by DevOps)
DB_HOST  
DB_NAME  
DB_USER  
DB_PASSWORD  
DB_PORT  

## EventBridge Schedule
Runs daily at 00:00 UTC  
Cron: `0 0 * * ? *`

## Notes for Developers
- This Lambda is developed and tested locally with mock data.
- No AWS access is required.
- Deployment is handled by team leads using the GitHub Actions workflow.