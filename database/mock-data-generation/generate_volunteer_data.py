import pandas as pd
from faker import Faker
import random

fake = Faker()

NUM_ROWS = 100

request_ids = list(range(1, 101))
user_ids = list(range(1, 101))

# volunteers_assigned
va_data = []
for i in range(NUM_ROWS):
    va_data.append({
        "id": i + 1,
        "request_id": random.choice(request_ids),
        "volunteer_id": random.choice(user_ids),
        "status": random.choice(["assigned", "completed", "pending"]),
        "assigned_at": fake.date_time_this_year()
    })

df_va = pd.DataFrame(va_data)

# volunteer_details
vd_data = []
for uid in user_ids:
    vd_data.append({
        "user_id": uid,
        "skills": random.choice(["medical", "delivery", "teaching", "cooking"]),
        "availability": random.choice(["full-time", "part-time", "weekends"]),
        "rating": round(random.uniform(3.0, 5.0), 1)
    })

df_vd = pd.DataFrame(vd_data)

df_va.to_csv("../mock_db/volunteers_assigned.csv", index=False)
df_vd.to_csv("../mock_db/volunteer_details.csv", index=False)

print("Done ✅")