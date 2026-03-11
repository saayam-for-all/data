Issue #100 - Lambda function for request category classification

This PR implements a Lambda function that classifies help requests into
existing categories and subcategories based on subject and description.

Features:
- Accepts subject and description as input
- Returns category, subcategory, confidence, and reasoning
- Uses rule-based NLP to minimize LLM cost
- Handles vague and empty input safely

Files added:
- lambda_function.py
- test_lambda.py

Related issue:
https://github.com/saayam-for-all/data/issues/100