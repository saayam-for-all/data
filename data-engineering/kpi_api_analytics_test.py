import json
import pandas as pd

import os


# LOAD CSV FILES

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

REQUEST_CSV = os.path.join(
    BASE_DIR,
    "..",
    "data-analytics",
    "sql",
    "Request_Table.csv"
)

CATEGORY_CSV = os.path.join(
    BASE_DIR,
    "..",
    "data-analytics",
    "sql",
    "help_category.csv"
)
STATUS_CSV = os.path.join(
    BASE_DIR,
    "..",
    "data-analytics",
    "sql",
    "Request_Status_data.csv"
)

def load_data():
    
    try:
        request_df = pd.read_csv(REQUEST_CSV)

    except Exception as e:
        print("Error loading request.csv:", str(e))
        request_df = pd.DataFrame()

    try:
        category_df = pd.read_csv(CATEGORY_CSV)

    except Exception as e:
        print("Error loading request_category.csv:", str(e))
        category_df = pd.DataFrame()
    
    try:
        status_df = pd.read_csv(STATUS_CSV)

    except Exception as e:
        print("Error loading status.csv:", str(e))
        status_df = pd.DataFrame()

    return request_df, category_df, status_df


# KPI 1
# Request Status Distribution


def get_request_status_distribution(request_df, status_df):

    try:

        if request_df.empty or status_df.empty:
            return [], 0

        # Merge request table with status lookup table
        merged_df = request_df.merge(
            status_df,
            on="req_status_id",
            how="left"
        )

        # Count by status name
        status_counts = (
            merged_df["req_status"]
            .value_counts()
            .reset_index()
        )

        status_counts.columns = ["status", "count"]

        distribution = [
            {
                "status": row["status"],
                "count": int(row["count"])
            }
            for _, row in status_counts.iterrows()
        ]

        total_requests = int(len(request_df))

        return distribution, total_requests

    except Exception as e:
        print("Error in status distribution:", str(e))
        return [], 0


# KPI 2
# Average Resolution Time by Category

def get_average_resolution_time_by_category(request_df, category_df):

    try:

        df = request_df.copy()

        df["submission_date"] = pd.to_datetime(df["submission_date"], errors="coerce")
        df["serviced_date"] = pd.to_datetime(df["serviced_date"], errors="coerce")

        # keep only valid rows
        df = df.dropna(subset=["submission_date", "serviced_date"])

        if df.empty:
            return []

        # absolute difference (data is inconsistent)
        df["resolution_hours"] = (
            (df["serviced_date"] - df["submission_date"]).dt.total_seconds().abs() / 3600
        )

        if "req_cat_id" not in df.columns:
            return []

        grouped = df.groupby("req_cat_id")["resolution_hours"].mean().reset_index()

        return [
            {
                "category": str(row["req_cat_id"]),
                "avg_hours": round(float(row["resolution_hours"]), 2)
            }
            for _, row in grouped.iterrows()
        ]

    except Exception as e:
        print("Resolution KPI error:", e)
        return []
    
# SLA

def get_sla_metadata():

    return {
        "target_days": 10,
        "target_hours": 240,
        "warning_days": 8.33,
        "warning_hours": 200
    }


# MAIN HANDLER

def lambda_handler(event, context):

    try:

        request_df, category_df, status_df = load_data()

        request_status_distribution, total_requests = (
    get_request_status_distribution(request_df, status_df)
)

        average_resolution_time_by_category = (
            get_average_resolution_time_by_category(
                request_df,
                category_df
            )
        )

        response = {
            "request_status_distribution":
                request_status_distribution,

            "total_requests":
                total_requests,

            "average_resolution_time_by_category":
                average_resolution_time_by_category,

            "sla":
                get_sla_metadata()
        }

        return {
            "statusCode": 200,
            "body": json.dumps(response)
        }

    except Exception as e:

        print("Lambda failed:", str(e))

        return {
            "statusCode": 500,
            "body": json.dumps({
                "request_status_distribution": [],
                "total_requests": 0,
                "average_resolution_time_by_category": [],
                "sla": get_sla_metadata()
            })
        }


# LOCAL TEST

if __name__ == "__main__":

    response = lambda_handler({}, {})

    print(json.dumps(response, indent=2))