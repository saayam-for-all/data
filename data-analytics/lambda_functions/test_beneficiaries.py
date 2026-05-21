import json
import pandas as pd

REQUEST_CSV = "/Users/prajaktawankhede/data/data-analytics/sql/Request_Table.csv"
USERS_CSV = "/Users/prajaktawankhede/data/data-analytics/sql/users.csv"
COUNTRY_CSV = "/Users/prajaktawankhede/data/data-analytics/sql/country.csv"


def lambda_handler(event, context):

    def load_request():
        df = pd.read_csv(REQUEST_CSV)
        df["submission_date"] = pd.to_datetime(df["submission_date"], errors="coerce")
        df["last_update_date"] = pd.to_datetime(df["last_update_date"], errors="coerce")
        return df

    def load_users():
        return pd.read_csv(USERS_CSV)

    def load_country():
        return pd.read_csv(COUNTRY_CSV)

    def aggregate_beneficiaries(interval_days):
        df = load_request()
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=interval_days)
        filtered = df[df["last_update_date"] > cutoff]
        return filtered["last_update_date"].dropna().tolist()

    def get_beneficiaries_dic(interval_days, group_by="day"):
        dates = aggregate_beneficiaries(interval_days)
        if not dates:
            return []

        df = pd.DataFrame(dates, columns=["last_update_date"])

        if group_by == "day":
            df_grouped = (
                df.groupby(df["last_update_date"].dt.date)
                .size()
                .reset_index(name="Count")
            )
            df_grouped["Date"] = df_grouped["last_update_date"].apply(
                lambda x: pd.Timestamp(x).isoformat()
            )
        elif group_by == "month":
            df_grouped = (
                df.groupby(df["last_update_date"].dt.to_period("M"))
                .size()
                .reset_index(name="Count")
            )
            df_grouped["Date"] = df_grouped["last_update_date"].apply(
                lambda x: x.to_timestamp().isoformat()
            )
        else:
            return []

        return df_grouped[["Date", "Count"]].to_dict("records")

    def aggregate_beneficiaries_country():
        try:
            requests = load_request()
            users = load_users()
            country = load_country()

            merged = requests.merge(users, left_on="req_user_id", right_on="user_id", how="inner")
            merged = merged.merge(country, on="country_id", how="inner")

            distinct = merged.drop_duplicates(subset=["req_user_id", "country_name"])
            df_grouped = distinct.groupby("country_name").size().reset_index(name="Count")
            return df_grouped.to_dict("records")
        except Exception as e:
            print(f"aggregate_beneficiaries_country error: {e}")
            return []

    def aggregate_help_requests(interval_days):
        df = load_request()
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=interval_days)
        filtered = df[df["submission_date"] > cutoff]
        return filtered["submission_date"].dropna().tolist()

    def get_help_requests_dic(interval_days, group_by="day"):
        dates = aggregate_help_requests(interval_days)
        if not dates:
            return []

        df = pd.DataFrame(dates, columns=["submission_date"])

        if group_by == "day":
            df_grouped = (
                df.groupby(df["submission_date"].dt.date)
                .size()
                .reset_index(name="Count")
            )
            df_grouped["Date"] = df_grouped["submission_date"].apply(
                lambda x: pd.Timestamp(x).isoformat()
            )
        elif group_by == "month":
            df_grouped = (
                df.groupby(df["submission_date"].dt.to_period("M"))
                .size()
                .reset_index(name="Count")
            )
            df_grouped["Date"] = df_grouped["submission_date"].apply(
                lambda x: x.to_timestamp().isoformat()
            )
        else:
            return []

        return df_grouped[["Date", "Count"]].to_dict("records")

    def aggregate_help_requests_country():
        try:
            requests = load_request()
            users = load_users()
            country = load_country()

            merged = requests.merge(users, left_on="req_user_id", right_on="user_id", how="inner")
            merged = merged.merge(country, on="country_id", how="inner")

            df_grouped = merged.groupby("country_name").size().reset_index(name="Count")
            return df_grouped.to_dict("records")
        except Exception as e:
            print(f"aggregate_help_requests_country error: {e}")
            return []

    response_body = {
        "7 days beneficiaries": get_beneficiaries_dic(7, "day"),
        "1 month beneficiaries": get_beneficiaries_dic(30, "day"),
        "1 year beneficiaries": get_beneficiaries_dic(365, "month"),
        "Country beneficiaries": aggregate_beneficiaries_country(),
        "7 days help requests": get_help_requests_dic(7, "day"),
        "1 month help requests": get_help_requests_dic(30, "day"),
        "1 year help requests": get_help_requests_dic(365, "month"),
        "Country help requests": aggregate_help_requests_country(),
    }

    return {
        "statusCode": 200,
        "body": json.dumps(response_body, indent=2)
    }


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(result["body"])