import boto3
import json
import zipfile
import os
import time

# ─────────────────────────────────────────────
# CONFIGURATION — update these before running
# ─────────────────────────────────────────────
LAMBDA_FUNCTION_NAME = 'auto-categorizer'
LAMBDA_FILES         = ['handler.py', 'categories.py', 'classifier.py', '__init__.py']
REGION               = 'us-east-1'
IAM_ROLE_NAME        = 'auto-categorizer-bedrock-role'
ZIP_FILE             = 'auto_categorizer.zip'

iam           = boto3.client('iam',    region_name=REGION)
lambda_client = boto3.client('lambda', region_name=REGION)
sts           = boto3.client('sts',    region_name=REGION)


def get_account_id():
    return sts.get_caller_identity()['Account']


def create_iam_role():
    print(f'\n[1/4] Setting up IAM role: {IAM_ROLE_NAME}')

    trust_policy = {
        'Version': '2012-10-17',
        'Statement': [{
            'Effect': 'Allow',
            'Principal': {'Service': 'lambda.amazonaws.com'},
            'Action': 'sts:AssumeRole'
        }]
    }

    try:
        response = iam.create_role(
            RoleName=IAM_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description='Role for auto-categorizer Lambda to access Bedrock'
        )
        role_arn = response['Role']['Arn']
        print(f'   IAM Role created: {role_arn}')

        iam.attach_role_policy(
            RoleName=IAM_ROLE_NAME,
            PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
        )
        print('   Attached: AWSLambdaBasicExecutionRole')

        iam.attach_role_policy(
            RoleName=IAM_ROLE_NAME,
            PolicyArn='arn:aws:iam::aws:policy/AmazonBedrockFullAccess'
        )
        print('   Attached: AmazonBedrockFullAccess')

        print('   Waiting 15 seconds for IAM role to propagate...')
        time.sleep(15)

    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=IAM_ROLE_NAME)['Role']['Arn']
        print(f'   IAM Role already exists, reusing: {role_arn}')

    return role_arn


def zip_lambda():
    print(f'\n[2/4] Zipping files -> {ZIP_FILE}')

    missing = [f for f in LAMBDA_FILES if not os.path.exists(f)]
    if missing:
        raise FileNotFoundError(
            f'ERROR: Missing files: {missing}. '
            f'Make sure all Lambda files are in the SAME folder as this deploy script.'
        )

    with zipfile.ZipFile(ZIP_FILE, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file in LAMBDA_FILES:
            zf.write(file)
            print(f'   Added: {file}')

    print(f'   Zipped successfully -> {ZIP_FILE}')

    with open(ZIP_FILE, 'rb') as f:
        return f.read()


def deploy_lambda(role_arn, zip_bytes):
    print(f'\n[3/4] Deploying Lambda: {LAMBDA_FUNCTION_NAME}')

    try:
        response = lambda_client.create_function(
            FunctionName=LAMBDA_FUNCTION_NAME,
            Runtime='python3.12',
            Role=role_arn,
            Handler='handler.lambda_handler',
            Code={'ZipFile': zip_bytes},
            Timeout=30,
            MemorySize=256,
            Description='Auto-categorizes help requests using Amazon Bedrock'
        )
        print('   Lambda created successfully!')
        print(f"   ARN: {response['FunctionArn']}")

    except lambda_client.exceptions.ResourceConflictException:
        print('   Function already exists. Updating code and handler...')
        response = lambda_client.update_function_code(
            FunctionName=LAMBDA_FUNCTION_NAME,
            ZipFile=zip_bytes
        )
        print(f"   Code updated! ARN: {response['FunctionArn']}")

        # Wait for code update to complete before updating config
        time.sleep(3)

        lambda_client.update_function_configuration(
            FunctionName=LAMBDA_FUNCTION_NAME,
            Handler='handler.lambda_handler'
        )
        print('   Handler updated to: handler.lambda_handler')


def smoke_test():
    print('\n[4/4] Running smoke test...')
    print('   Waiting 5 seconds for Lambda to be ready...')
    time.sleep(5)

    test_payload = {
        'subject': 'I need food for my family',
        'description': 'We have not eaten in two days and I have three children at home.'
    }

    response = lambda_client.invoke(
        FunctionName=LAMBDA_FUNCTION_NAME,
        InvocationType='RequestResponse',
        Payload=json.dumps(test_payload)
    )

    result = json.loads(response['Payload'].read())

    print('\n   Test Input:')
    print(f"      Subject:     {test_payload['subject']}")
    print(f"      Description: {test_payload['description']}")
    print('\n   Lambda Response:')
    print(json.dumps(result, indent=6))


if __name__ == '__main__':
    print('=' * 55)
    print('  Auto-Categorizer Lambda Deployment Script')
    print('=' * 55)

    account_id = get_account_id()
    print(f'\nConnected to AWS Account: {account_id} | Region: {REGION}')

    try:
        role_arn  = create_iam_role()
        zip_bytes = zip_lambda()
        deploy_lambda(role_arn, zip_bytes)
        smoke_test()

        print('\n' + '=' * 55)
        print('  Deployment complete!')
        print(f'  Function Name : {LAMBDA_FUNCTION_NAME}')
        print(f'  Region        : {REGION}')
        print('=' * 55)

    except FileNotFoundError as e:
        print(f'\n{e}')
    except Exception as e:
        print(f'\nDeployment failed: {e}')
        raise
    finally:
        if os.path.exists(ZIP_FILE):
            os.remove(ZIP_FILE)
            print(f'\nCleaned up temporary {ZIP_FILE}')