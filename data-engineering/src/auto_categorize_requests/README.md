# Auto-Categorize Requests — Lambda Function

## Overview

This Lambda function automatically classifies incoming help requests based on their `subject` and `description` using Amazon Bedrock (Claude 3 Haiku). It returns the most appropriate category and subcategory from the platform's predefined list, along with a confidence score and reasoning.

This is a suggestion engine only — it does not overwrite user-selected categories. Downstream consumers can use the confidence score to decide whether to auto-assign or flag for human review.

---

## Files

| File | Description |
|------|-------------|
| `lambda_function.py` | Lambda entry point — contains all classification logic |
| `requirements.txt` | Lambda-specific dependencies |
| `__init__.py` | Makes this folder a Python package |

---

## Lambda Input

```json
{
  "subject": "I need a place to stay tonight",
  "description": "I just lost my apartment and I'm on the streets. I have two kids with me and we need somewhere safe to sleep."
}
```

## Lambda Output

```json
{
  "statusCode": 200,
  "body": {
    "category": "Housing Assistance",
    "subcategory": "Looking for Rental",
    "confidence": 0.92,
    "reasoning": "Request describes urgent need for housing after losing apartment with dependents."
  }
}
```

---

## Valid Categories & Subcategories

| Category | Subcategories |
|----------|--------------|
| Clothing Assistance | Donate Clothes, Borrow Clothes, Emergency Clothing Assistance, Tailoring |
| Education & Career Support | College Application Help, SOP & Essay Review, Tutoring, Scholarship Knowledge, Study Group Formation, Career Guidance, Education Resource Sharing |
| Elderly Community Assistance | Senior Relocation Support, Digital Support for Seniors, Medication Management, Medical Devices Setup, Errands Events & Transportation, Transportation for Appointments, Scheduling Appointments or Tasks, Social Connection, Meal Support |
| Food & Essentials | Food Assistance, Grocery Shopping & Delivery, Cooking Help |
| Healthcare & Wellness | Medical Consultation, Medicine Delivery, Mental Wellbeing Support, Medication Reminders, Health Education Guidance |
| Housing Assistance | Lease Support, Tenant Rent Support, Repair & Maintenance Support, Utilities Setup Support, Looking for Rental, Find a Roommate, Move-in Help, Packers & Movers Support, Buy Household Items, Sell Household Items |
| General | No subcategories — used as fallback when request is vague or unclear |

---

## How It Works

1. Lambda receives `subject` and `description` as input
2. Constructs a prompt with the full valid categories list as context
3. Calls Amazon Bedrock (Claude 3 Haiku) to classify the request
4. Validates the response against the predefined list — falls back to `General` if invalid
5. Returns `category`, `subcategory`, `confidence`, and `reasoning`

---

## Edge Cases Handled

- **Vague input** — returns `General` with lower confidence
- **Missing subject or description** — substitutes a placeholder and still classifies
- **Both fields empty** — returns `400` error cleanly
- **Multilingual input** — Bedrock translates and classifies normally
- **Model hallucination** — validation layer forces fallback to `General` if response is not in the predefined list

---

## Deployment

Team leads handle deployment. The entry point is `lambda_function.lambda_handler`.

**IAM role requires:**
- `AmazonBedrockFullAccess`
- `AWSLambdaBasicExecutionRole`

**Bedrock model required:** Claude 3 Haiku (`anthropic.claude-3-haiku-20240307-v1:0`) — ensure model access is enabled in your AWS account.
