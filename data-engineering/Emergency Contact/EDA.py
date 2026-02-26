import pandas as pd
import re

# Step 1: Load the CSV data into a DataFrame
df = pd.read_csv('emergency_numbers.csv')

# Step 2: Remove duplicate header rows
# Keep only the first occurrence of the headers
df = df[df['Country'] != 'Country']

# Step 3: Clean up special characters (e.g., references like [2], [3])
# Use a regex to remove square brackets and their contents
df = df.replace(to_replace=r'\[\d+\]', value='', regex=True)

# Step 4: Handle missing data
# Replace empty strings with None (or NaN in pandas)
df = df.replace('', None)

# Step 5: Format the data consistently
# Example: Remove leading/trailing whitespace, fix case, etc.
df['Country'] = df['Country'].str.strip()
df['Police'] = df['Police'].str.strip()
df['Ambulance'] = df['Ambulance'].str.strip()
df['Fire'] = df['Fire'].str.strip()
df['Notes'] = df['Notes'].str.strip()

# Optional: Normalize the case of the data (e.g., all uppercase)
df['Country'] = df['Country'].str.title()

# Step 6: Save the cleaned DataFrame to a new CSV file
df.to_csv('cleaned_emergency_numbers.csv', index=False)

print("Data has been cleaned and saved to 'cleaned_emergency_numbers.csv'.")
