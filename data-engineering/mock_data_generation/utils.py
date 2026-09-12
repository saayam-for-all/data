import random

def generate_user_id(seq_id: int) -> str:
    padded = str(seq_id).zfill(15)
    groups = [padded[i:i + 3] for i in range(0, 15, 3)]
    return "SID-00-" + "-".join(groups)

def generate_org_id(seq_id: int) -> str:
    padded = str(seq_id).zfill(13)
    return f"ORG-{padded[0:3]}-{padded[3:6]}-{padded[6:9]}-{padded[9:13]}"

def generate_state_id(country_code: str, index: int) -> str:
    return f"{country_code}-ST-{str(index).zfill(3)}"

def random_point_near(lat: float, lon: float, spread: float = 2.0):
    return (
        round(lat + random.uniform(-spread, spread), 6),
        round(lon + random.uniform(-spread, spread), 6),
    )

def random_timestamp(faker, start_date="-2y", end_date="now"):
    dt = faker.date_time_between(start_date=start_date, end_date=end_date)
    return dt.strftime("%Y-%m-%d %H:%M:%S")