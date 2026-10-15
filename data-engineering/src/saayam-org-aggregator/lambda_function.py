import json
import logging
import math
from helpers import get_ai_orgs, get_orgs_from_db, merge_organizations, run_query
from concurrent.futures import ThreadPoolExecutor

import db_columns
from beneficiary_location import fetch_state_names, resolve_beneficiary_location
from distance import add_distance_columns, build_db_org_address, build_genai_org_address

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _result_or_none(future, source):
    """Return a future's DataFrame, or None (logged) if it failed or is empty."""
    try:
        df = future.result()
    except Exception as e:
        logger.error("%s organizations unavailable: %s", source, e)
        return None, e
    return (df if df is not None and len(df) > 0 else None), None


def _resolve_origin(request_id, beneficiary_id):
    """Beneficiary (lat, lon) or None. Never raises."""
    try:
        location = resolve_beneficiary_location(run_query, request_id, beneficiary_id)
    except Exception:
        logger.exception("Beneficiary location resolution failed")
        return None
    if location is None:
        logger.info("Beneficiary location unknown (request_id=%s)", request_id)
        return None
    logger.info("Beneficiary location from %s", location.source)
    return location.point


def _add_db_distances(df, origin):
    state_names = {}
    if origin is not None:
        state_column = next((c for c in db_columns.ORG_STATE_COLUMNS if c in df.columns), None)
        if state_column is not None:
            state_names = fetch_state_names(run_query, df[state_column].tolist())
    return add_distance_columns(
        df, origin,
        lambda row: build_db_org_address(row, state_names),
        db_columns.ORG_ONLINE_FLAG_COLUMNS,
    )


def _json_safe(value):
    """NaN/inf -> None so json.dumps always emits valid JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


# handle the lambda function call
def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")
        category = body.get("category")
        # Optional: used only to measure distance from the beneficiary (#433).
        request_id = body.get("request_id")
        beneficiary_id = body.get("beneficiary_id")

        if not location or not category:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'location and category are required fields'})
            }

        # db_organizations = get_orgs_from_db(location, category)
        # genAI_organizations = get_ai_orgs(subject, description, location)

        #Implemented parallelization to speed up the reponse

        with ThreadPoolExecutor() as executor:
            db_future = executor.submit(get_orgs_from_db, location, category)
            ai_future = executor.submit(get_ai_orgs, subject, description, location)
            origin_future = executor.submit(_resolve_origin, request_id, beneficiary_id)

            db_organizations, db_error = _result_or_none(db_future, "DB")
            genAI_organizations, ai_error = _result_or_none(ai_future, "GenAI")
            origin = origin_future.result()

        # One source failing is recoverable; both failing is not.
        if db_error is not None and ai_error is not None:
            raise Exception(f'{db_error}; {ai_error}')

        if db_organizations is not None:
            db_organizations = _add_db_distances(db_organizations, origin)
        if genAI_organizations is not None:
            genAI_organizations = add_distance_columns(
                genAI_organizations, origin, build_genai_org_address,
                db_columns.GENAI_ONLINE_FLAG_COLUMNS,
            )

        combined_list = merge_organizations(db_organizations, genAI_organizations)
        records = [
            {key: _json_safe(value) for key, value in record.items()}
            for record in combined_list.to_dict(orient='records')
        ]

        return {
            'statusCode': 200,
            'headers': {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": '*'
            },
            'body': json.dumps(records)
        }

    except json.JSONDecodeError as e:
        return {'statusCode': 400, 'body': json.dumps({'error': f'Invalid JSON in request body: {str(e)}'})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'Internal server error: {str(e)}'})}
