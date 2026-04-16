#import libraries
import pandas as pd 
import random 
from datetime import timedelta, datetime 

#column generation
fraud_request_id = []
for i in range(1,801):
    fraud_request_id.append(i)

def random_timestamp_within_days(days=180):
    start = datetime.now() - timedelta(days=days)
    random_seconds = random.randint(0, days * 24 * 60 * 60)
    return start + timedelta(seconds=random_seconds)

request_timedate = []

for i in range(1,801):
    request_dt = random_timestamp_within_days()
    request_timedate.append(request_dt.strftime("%Y-%m-%d %H:%M:%S"))

fraud_reasons = [
    "Suspicious payment activity detected",
    "Multiple failed login attempts",
    "Unrecognized transaction reported",
    "Possible account takeover concern",
    "Identity verification mismatch",
    "Reported unauthorized access",
    "Abnormal account activity detected",
    "Duplicate suspicious request flagged"
]

reason= []
for i in range(1,801):
    reason.append(random.choice(fraud_reasons))

user_id = [f"U{str(i).zfill(3)}" for i in range(1,801)]
user_ids = [random.choice(user_id) for i in range(1,801)]

#create dataframe
fraud_requests = pd.DataFrame({"fraud_request_id":fraud_request_id, "user_id":user_ids, "request_datetime":request_timedate,"reason":reason})


#change datatypes
fraud_requests['user_id'] = fraud_requests['user_id'].astype("string")
fraud_requests['request_datetime'] = pd.to_datetime(fraud_requests['request_datetime'])
fraud_requests['reason'] = fraud_requests['reason'].astype("string")

#sanity check
fraud_requests.dtypes
fraud_requests.isnull().sum()
fraud_requests.duplicated().sum()

#convert to csv file
fraud_requests.to_csv("fraud_requests.csv",index=False)