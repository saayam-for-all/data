import random
from datetime import datetime, timedelta


def random_timestamp(start_date="2026-01-01", end_date="2026-09-01"):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    delta_seconds = int((end - start).total_seconds())
    random_seconds = random.randint(0, delta_seconds)

    return start + timedelta(seconds=random_seconds)


def postgres_timestamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def make_user_id(number):
    padded = str(number).zfill(15)

    return (
        "SID-00-"
        + padded[0:3]
        + "-"
        + padded[3:6]
        + "-"
        + padded[6:9]
        + "-"
        + padded[9:12]
        + "-"
        + padded[12:15]
    )


def make_org_id(number):
    padded = str(number).zfill(13)

    return (
        "ORG-"
        + padded[0:3]
        + "-"
        + padded[3:6]
        + "-"
        + padded[6:9]
        + "-"
        + padded[9:13]
    )


def make_point(longitude, latitude):
    return f"POINT({longitude:.6f} {latitude:.6f})"


def nearby_point(longitude, latitude, spread=0.03):
    new_longitude = longitude + random.uniform(-spread, spread)
    new_latitude = latitude + random.uniform(-spread, spread)

    return make_point(new_longitude, new_latitude)