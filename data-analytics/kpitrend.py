import pandas as pd
import matplotlib.pyplot as plt


# Load Data
users = pd.read_csv("database/mock_db/users.csv")
requests = pd.read_csv("database/mock_db/request.csv")

# Convert date column
requests["created_at"] = pd.to_datetime(requests["created_at"])

# Create Month column
requests["month"] = requests["created_at"].dt.to_period("M").astype(str)

# KPI Calculation
kpis = {
    "Minimum Resolution Time": round(requests["resolution_time_hours"].min(), 2),
    "Maximum Resolution Time": round(requests["resolution_time_hours"].max(), 2),
    "Average Resolution Time": round(requests["resolution_time_hours"].mean(), 2)
}

print("\nKPIs:")
print(kpis)

# Monthly Trend Analysis
monthly_avg = (
    requests.groupby("month")["resolution_time_hours"]
    .mean()
    .reset_index()
    .sort_values("month")
)

print("\nMonthly Trend:")
print(monthly_avg)

# Visualization
plt.plot(monthly_avg["month"], monthly_avg["resolution_time_hours"], marker='o')
plt.title("Average Resolution Time Trend")
plt.xlabel("Month")
plt.ylabel("Avg Resolution Time (Hours)")
plt.xticks(rotation=45)
plt.show()

# State-wise analysis
merged = requests.merge(users, left_on="req_user_id", right_on="user_id", how="left")

state_analysis = (
    merged.groupby("state_id")["resolution_time_hours"]
    .agg(["min", "max", "mean", "count"])
    .reset_index()
)

state_analysis.rename(columns={
    "min": "min_time",
    "max": "max_time",
    "mean": "avg_time",
    "count": "total_requests"
}, inplace=True)

print(state_analysis)

state_analysis = state_analysis.sort_values(by="avg_time")

import matplotlib.pyplot as plt

plt.bar(state_analysis["state_id"].astype(str), state_analysis["avg_time"])

plt.title("Average Resolution Time by State")
plt.xlabel("State ID")
plt.ylabel("Avg Resolution Time (Hours)")
plt.xticks(rotation=45)

plt.show()

state_lookup = pd.read_csv("lookup_tables/state.csv")

merged = merged.merge(state_lookup, on="state_id", how="left")

state_analysis = (
    merged.groupby("state_name")["resolution_time_hours"]
    .mean()
    .reset_index()
    .sort_values(by="resolution_time_hours")
)