#import libraries
import pandas as pd 
import random 
from datetime import timedelta, datetime 

#column generation
user_id_list = [f"U{str(i).zfill(3)}" for i in range(1,30001)]
notification_id = [i for i in range(1,30001)]
type_id_list = [i for i in range(1,30001)]
channel_id_list = [i for i in range(1,30001)]

notification_messages = [
    "Your fraud report has been received and is under review.",
    "Suspicious activity was detected on your account.",
    "Please review your recent transactions for any unauthorized activity.",
    "Your account has been temporarily restricted due to unusual behavior.",
    "We detected a login attempt from an unrecognized device.",
    "Your password was recently changed successfully.",
    "A new device has been added to your account.",
    "Your fraud request has been successfully submitted.",
    "Your fraud request is currently being processed.",
    "Your account has been secured after suspicious activity.",
    "Please verify your identity to continue using your account.",
    "Multiple failed login attempts were detected on your account.",
    "A transaction on your account requires your confirmation.",
    "Your account details have been updated successfully.",
    "We have resolved your reported issue. Please review your account.",
    "Your account has been unlocked. You may now log in.",
    "Your request has been escalated for further investigation.",
    "A security alert has been issued for your account.",
    "We noticed unusual activity and have notified our security team.",
    "Your account has been flagged for review by our fraud team."
]

status_list= ['Read','Unread']
status= [random.choice(status_list) for i in range(1,30001)]
messages = [random.choice(notification_messages) for i in range(1,30001)]

created_at = []
update_at =[]

for i in range(1,30001):
    created_val = datetime.now() - timedelta(days=random.randint(0,180),hours=random.randint(0,180),minutes=random.randint(0,59)) 
    update_delay = timedelta(hours=random.randint(0,72),minutes=random.randint(0,59))

    updated_val = created_val + update_delay
    created_at.append(created_val.strftime("%Y-%m-%d %H:%M:%S"))
    update_at.append(updated_val.strftime("%Y-%m-%d %H:%M:%S"))

user_id = [random.choice(user_id_list) for i in range(1,30001)]
type_id = [random.choice(type_id_list) for i in range(1,30001)]
channel_id = [random.choice(channel_id_list) for i in range(1,30001)]

#create dataframe
notifications = pd.DataFrame({"notification_id":notification_id,"user_id":user_id,"type_id":type_id,"channel_id":channel_id,"message":messages,"status":status,"created_at":created_at,"updated_at":update_at})

#change datatypes
notifications['user_id'] = notifications['user_id'].astype("string")
notifications['created_at'] = pd.to_datetime(notifications['created_at'])
notifications['updated_at'] = pd.to_datetime(notifications['updated_at'])
notifications['message'] = notifications['message'].astype("string")
notifications['status'] = notifications['status'].astype("string")

#sanity check
notifications.dtypes
notifications.isnull().sum()
notifications.duplicated().sum()

#convert to csv file
notifications.to_csv("notifications.csv",index=False)