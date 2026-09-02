import json
from contextlib import contextmanager

import pandas as pd
import pg8000
from aws_lambda_powertools.utilities import parameters

_creds = json.loads(
    parameters.get_parameter(
        "/dev/saayam/db/Virginia/Analytics/user", decrypt=True, max_age=3600
    )
)
_db_name = _creds["DATABASE NAME"]


@contextmanager
def __get_db_conn():
    db_conn = pg8000.connect(
        host=_creds["HOST"],
        user=_creds["USERNAME"],
        password=_creds["PASSWORD"],
        database=_db_name,
        port=_creds["PORT"],
        ssl_context=True,
    )
    try:
        yield db_conn
    finally:
        db_conn.close()


def validate_request_id(request_id):
    """
    Checks if request id is present in the DB or not.
    """
    with __get_db_conn() as db_conn:
        df = pd.read_sql(
            f"SELECT 1 FROM {_db_name}.requests WHERE req_id = '{request_id}';", db_conn
        )
        return not df.empty


def get_assigned_volunteer_id(request_id):
    """
    Retrieves the assigned lead volunteer id for the given request id.
    """
    with __get_db_conn() as db_conn:
        df = pd.read_sql(
            f"SELECT lead_volunteer_id FROM {_db_name}.requests WHERE req_id = '{request_id}';",
            db_conn,
        )
        return df.iloc[0, 0]


def get_volunteer_details(volunteer_id):
    """
    Retrieves the volunteer details for the given volunteer id.
    """
    with __get_db_conn() as db_conn:
        # Required columns not known yet
        df = pd.read_sql(
            f"SELECT * FROM {_db_name}.users WHERE user_id = '{volunteer_id};'", db_conn
        )
        return df.to_dict(orient="records")[0]


def get_volunteer_status(volunteer_id):
    """
    Retrieves the status of volunteer for the given volunteer id.
    """
    with __get_db_conn() as db_conn:
        df = pd.read_sql(
            f"""
                SELECT
                    user_status
                FROM {_db_name}.users u
                    JOIN {_db_name}.user_status us
                    ON u.user_status_id = us.user_status_id
                WHERE u.user_id = '{volunteer_id}';
            """,
            db_conn,
        )
        return df.iloc[0, 0]


def get_volunteer_skills(volunteer_id):
    """
    Retrieves the skills of volunteer for the given volunteer id.
    """
    SKILL_COLUMN = "cat_name"
    with __get_db_conn() as db_conn:
        df = pd.read_sql(
            f"""
                SELECT
                    {SKILL_COLUMN}
                FROM {_db_name}.user_skills us
                    JOIN {_db_name}.help_categories hc
                    ON us.cat_id = hc.cat_id
                WHERE us.user_id = '{volunteer_id}';
            """,
            db_conn,
        )
        return df.to_dict(orient="list")[SKILL_COLUMN]
