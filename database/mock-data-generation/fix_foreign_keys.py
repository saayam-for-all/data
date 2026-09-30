import pandas as pd
import random

# Load generated CSVs
users_df = pd.read_csv("../mock_db/users.csv")
request_df = pd.read_csv("../mock_db/request.csv")
comments_df = pd.read_csv("../mock_db/request_comments.csv")
volunteers_df = pd.read_csv("../mock_db/volunteer_details.csv")
assigned_df = pd.read_csv("../mock_db/volunteers_assigned.csv")

# Fix request table
request_df['req_user_id'] = request_df['req_user_id'].apply(lambda x: random.choice(users_df['user_id']))
request_df.to_csv("../mock_db/request.csv", index=False)

# Fix comments table
comments_df['req_id'] = comments_df['req_id'].apply(lambda x: random.choice(request_df['req_id']))
comments_df['commenter_id'] = comments_df['commenter_id'].apply(lambda x: random.choice(users_df['user_id']))
comments_df.to_csv("../mock_db/request_comments.csv", index=False)

# Fix volunteer details table
volunteers_df['user_id'] = volunteers_df['user_id'].apply(lambda x: random.choice(users_df['user_id']))
volunteers_df.to_csv("../mock_db/volunteer_details.csv", index=False)

# Fix volunteer assignments
assigned_df['request_id'] = assigned_df['request_id'].apply(lambda x: random.choice(request_df['req_id']))
assigned_df['volunteer_id'] = assigned_df['volunteer_id'].apply(lambda x: random.choice(volunteers_df['user_id']))
assigned_df.to_csv("../mock_db/volunteers_assigned.csv", index=False)

print("All foreign keys fixed successfully!")