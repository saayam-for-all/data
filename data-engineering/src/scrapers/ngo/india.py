import requests
import pandas as pd
import time
from bs4 import BeautifulSoup

# Base URL for the request
base_url = "https://ngodarpan.gov.in/index.php/ajaxcontroller/search_index_new/"

# Headers required for the request
headers = {
    "Accept": "*/*",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Cookie": "ci_session=lbd52vialfao5sfecjpgbl42dgkhnb0m; ngd_csrf_cookie_name=140086eb215f2d7c09f14b2d605f54a8",
    "Origin": "https://ngodarpan.gov.in",
    "Referer": "https://ngodarpan.gov.in/index.php/search/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}

# Data payload for the request
payload_template = {
    "state_search": "",
    "district_search": "",
    "sector_search": "null",
    "ngo_type_search": "null",
    "ngo_name_search": "",
    "unique_id_search": "",
    "view_type": "detail_view",
    "csrf_test_name": "140086eb215f2d7c09f14b2d605f54a8",  # Change this value if needed
}


# Function to get the data for a specific page
def fetch_page_data(page_number):
    payload = payload_template.copy()
    response = requests.post(base_url + str(page_number), headers=headers, data=payload)

    if response.status_code == 200:
        return response.content
    else:
        print(f"Error fetching page {page_number}: Status code {response.status_code}")
        return None


# Function to extract relevant data from the response
def parse_data(response):
    # Extract relevant fields from the response.
    # This is a placeholder, you will need to adjust this according to the actual response format.
    soup = BeautifulSoup(response, "html.parser")
    table = soup.find("table", {"id": "example"})  # Locating the table by its ID
    rows = table.find_all("tr")  # Get all rows from the table
    parsed_data = []
    for row in rows:
        header = cols = row.find_all("th")
        if len(header) != 0:
            data = [col.text for col in header]
        else:
            cols = row.find_all("td")  # Get all columns
            data = [col.text for col in cols]  # Extract text from each column
            parsed_data.append(
                {
                    "S.No": data[0],
                    "Name of VO/NGO": data[1],
                    "Registration No.,City & State": data[2],
                    "Address": data[3],
                    "Sectors working in": data[4],
                }
            )
        print(data)
    print(parsed_data)
    return parsed_data


# Initialize a list to store all the results
all_data = []
last_page = 260569

# Loop over multiple pages and fetch data
for page in range(1, last_page):  # Change the range as needed
    # start_time = time.time()
    print(f"Fetching data from page {page}...")
    response = fetch_page_data(page)
    if response:
        page_data = parse_data(response)
        all_data.extend(page_data)
    else:
        break

df = pd.DataFrame(all_data)

# Save the data to a CSV file
df.to_csv("ngo_data.csv", index=False)

print("Data saved to ngo_data.csv")
