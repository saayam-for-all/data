import boto3
import json
import time
import logging
import os
from datetime import datetime

LAMBDA_FUNCTION_NAME = 'auto-categorizer'
REGION = 'us-east-1'

lambda_client = boto3.client('lambda', region_name=REGION)
sts = boto3.client('sts', region_name=REGION)

# ─────────────────────────────────────────────
# LOGGING SETUP — writes to both console and log file
# ─────────────────────────────────────────────
LOG_FILE = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logger = logging.getLogger('auto_categorizer_test')
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(message)s'))

# File handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(message)s'))

logger.addHandler(console_handler)
logger.addHandler(file_handler)


def get_masked_account_id():
    account_id = sts.get_caller_identity()['Account']
    # Mask middle digits — show first 3 and last 2 only e.g. 944*****21
    return account_id[:3] + '*' * (len(account_id) - 5) + account_id[-2:]


TEST_CASES = [
    {'id': 1, 'label': 'Clear Food Request',
     'input': {'subject': 'Need groceries urgently', 'description': 'I am a single mother and cannot afford groceries. My kids need food.'},
     'expected_category': 'Food & Essentials'},
    {'id': 2, 'label': 'Housing - Looking for Rental',
     'input': {'subject': 'Looking for an apartment to rent', 'description': 'I recently moved to the city and need an affordable rental apartment.'},
     'expected_category': 'Housing Assistance'},
    {'id': 3, 'label': 'Education - College Application',
     'input': {'subject': 'Need help with college application', 'description': 'I am a high school senior applying to universities and need help writing my SOP.'},
     'expected_category': 'Education & Career Support'},
    {'id': 4, 'label': 'Healthcare - Medical Consultation',
     'input': {'subject': 'I need to speak to a doctor', 'description': 'I have been having chest pain for two days but cannot afford a hospital visit.'},
     'expected_category': 'Healthcare & Wellness'},
    {'id': 5, 'label': 'Elderly Assistance',
     'input': {'subject': 'Help for my elderly father', 'description': 'My 80 year old father lives alone and needs help with daily errands and doctor appointments.'},
     'expected_category': 'Elderly Community Assistance'},
    {'id': 6, 'label': 'Clothing Donation Request',
     'input': {'subject': 'Need warm clothes for winter', 'description': 'I lost my job and cannot buy winter clothes for myself and my two children.'},
     'expected_category': 'Clothing Assistance'},
    {'id': 7, 'label': 'Vague Request - edge case',
     'input': {'subject': 'I need some help', 'description': 'Things have been really tough lately and I just need some assistance.'},
     'expected_category': 'General'},
    {'id': 8, 'label': 'Multilingual Spanish - edge case',
     'input': {'subject': 'Necesito comida para mi familia', 'description': 'No hemos comido en dos dias. Tengo tres hijos en casa y necesitamos ayuda.'},
     'expected_category': 'Food & Essentials'},
    {'id': 9, 'label': 'Missing Description - edge case',
     'input': {'subject': 'Need help finding a roommate', 'description': ''},
     'expected_category': 'Housing Assistance'},
    {'id': 10, 'label': 'Both Fields Empty - edge case',
     'input': {'subject': '', 'description': ''},
     'expected_category': None},
    {'id': 11, 'label': 'Career Guidance',
     'input': {'subject': 'Confused about my career path', 'description': 'I recently graduated with a CS degree but unsure which field to pursue. Need career advice.'},
     'expected_category': 'Education & Career Support'},
    {'id': 12, 'label': 'Mental Health - edge case',
     'input': {'subject': 'Feeling very anxious and depressed', 'description': 'I have been struggling with anxiety for months and cannot afford therapy.'},
     'expected_category': 'Healthcare & Wellness'},
]


def invoke_lambda(payload):
    start = time.time()
    response = lambda_client.invoke(
        FunctionName=LAMBDA_FUNCTION_NAME,
        InvocationType='RequestResponse',
        Payload=json.dumps(payload)
    )
    elapsed = round(time.time() - start, 2)
    result = json.loads(response['Payload'].read())
    return result, elapsed


def run_tests():
    masked_account = get_masked_account_id()

    logger.info('=' * 65)
    logger.info('  Auto-Categorizer Lambda Test Suite')
    logger.info(f'  Function : {LAMBDA_FUNCTION_NAME}')
    logger.info(f'  Region   : {REGION}')
    logger.info(f'  Account  : {masked_account}')
    logger.info(f'  Run At   : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    logger.info(f'  Log File : {LOG_FILE}')
    logger.info('=' * 65)

    passed = 0
    failed = 0
    slow = 0
    elapsed_times = []

    for test in TEST_CASES:
        logger.info(f"\n[Test {test['id']}] {test['label']}")
        logger.info(f"  Subject     : {test['input']['subject'] or '(empty)'}")
        logger.info(f"  Description : {(test['input']['description'] or '(empty)')[:80]}")

        try:
            result, elapsed = invoke_lambda(test['input'])
            elapsed_times.append(elapsed)
            status_code = result.get('statusCode')
            body = result.get('body', {})
            if isinstance(body, str):
                body = json.loads(body)

            if status_code == 400:
                if test['expected_category'] is None:
                    logger.info('  Status      : 400 Bad Request (expected for empty input)')
                    logger.info(f'  Result      : PASS  ({elapsed}s)')
                    passed += 1
                else:
                    logger.info('  Status      : 400 (unexpected)')
                    logger.info(f'  Result      : FAIL  ({elapsed}s)')
                    failed += 1
            else:
                category   = body.get('category')
                subcategory = body.get('subcategory')
                confidence = body.get('confidence')
                reasoning  = body.get('reasoning', '')

                logger.info(f'  Category    : {category}')
                logger.info(f'  Subcategory : {subcategory}')
                logger.info(f'  Confidence  : {confidence}')
                logger.info(f'  Reasoning   : {str(reasoning)[:100]}')
                logger.info(f'  Time        : {elapsed}s')

                if elapsed > 5:
                    logger.info('  WARNING     : Slow response > 5s')
                    slow += 1

                if test['expected_category'] and category == test['expected_category']:
                    logger.info('  Result      : PASS')
                    passed += 1
                elif test['expected_category'] is None:
                    logger.info('  Result      : PASS (no expected category)')
                    passed += 1
                else:
                    logger.info(f"  Result      : FAIL (expected '{test['expected_category']}', got '{category}')")
                    failed += 1

        except Exception as e:
            logger.info(f'  ERROR : {e}')
            failed += 1

    avg = round(sum(elapsed_times) / len(elapsed_times), 2) if elapsed_times else 0

    logger.info('\n' + '=' * 65)
    logger.info('  TEST SUMMARY')
    logger.info('=' * 65)
    logger.info(f'  Total   : {len(TEST_CASES)}')
    logger.info(f'  Passed  : {passed}')
    logger.info(f'  Failed  : {failed}')
    logger.info(f'  Slow    : {slow}')
    logger.info(f'  Avg Time: {avg}s')
    logger.info(f'  Account : {masked_account}')
    logger.info('=' * 65)
    logger.info(f'\nLog saved to: {LOG_FILE}')


if __name__ == '__main__':
    run_tests()