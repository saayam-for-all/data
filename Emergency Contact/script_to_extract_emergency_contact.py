import requests
from bs4 import BeautifulSoup
import pandas as pd

# Step 1: Load the HTML data (from a local file or URL)
url = 'https://en.wikipedia.org/wiki/List_of_emergency_telephone_numbers'
response = requests.get(url)
html = response.text

# Step 2: Parse the HTML
soup = BeautifulSoup(html, 'html.parser')

# Step 3: Find all the tables with the class 'wikitable'
tables = soup.find_all('table', {'class': 'wikitable'})

# Initialize a list to hold all the rows from all tables
all_rows = []

# Step 4: Loop through each table and extract data
for table in tables:
    headers = []
    for th in table.find_all('th'):
        headers.append(th.get_text(strip=True))

    # Extract the table rows
    rows = []
    for tr in table.find_all('tr'):
        cells = tr.find_all(['td', 'th'])
        row = [cell.get_text(strip=True) for cell in cells]
        if len(row) == len(headers):  # Ensure the row has the correct number of columns
            rows.append(row)
    
    # Append rows to all_rows
    all_rows.extend(rows)

# Step 5: Convert the aggregated data into a DataFrame
df = pd.DataFrame(all_rows, columns=headers)

# Step 6: Save the DataFrame to a CSV file
df.to_csv('emergency_numbers.csv', index=False)

print("Data from all tables has been extracted and saved to 'emergency_numbers.csv'.")
