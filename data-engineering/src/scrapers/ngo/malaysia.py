import requests
from bs4 import BeautifulSoup
import pandas as pd

# Base URL for the NGO listings page (with page parameter)
base_url = "https://ngobase.org/c/MY/malaysia-ngos-charities?page={}"


# Function to extract data from a single page
def scrape_page(url):
    # Send a request to the page
    response = requests.get(url)
    response.raise_for_status()  # Check for request errors

    # Parse HTML content
    soup = BeautifulSoup(response.text, "html.parser")

    # Find all NGO listings
    ngos = soup.find_all("div", class_="my_border ngo_listing_div")

    # Lists to store extracted data
    names = []
    work_areas = []
    websites = []
    facebook_links = []
    locations = []

    # Loop through each NGO listing
    for ngo in ngos:
        # Extract the NGO name
        name_tag = ngo.find("h3", class_="ngo_name")
        name = name_tag.get_text(strip=True) if name_tag else "N/A"

        # Extract work areas and sub-areas
        work_area_tags = ngo.find_all("li", class_="ngo_listing_work_area_li")
        work_area_list = [wa.get_text(" -> ", strip=True) for wa in work_area_tags]
        work_area = ", ".join(work_area_list) if work_area_list else "N/A"

        # Extract website and Facebook links
        website_tag = ngo.find("a", title=lambda x: x and "website" in x.lower())
        facebook_tag = ngo.find("a", title=lambda x: x and "facebook" in x.lower())
        website = website_tag["href"] if website_tag else "N/A"
        facebook = facebook_tag["href"] if facebook_tag else "N/A"

        # Extract location
        location_tags = ngo.find_all("a", class_="listing_locations")
        location = (
            ", ".join([loc.get_text(strip=True) for loc in location_tags])
            if location_tags
            else "N/A"
        )

        # Append data to lists
        names.append(name)
        work_areas.append(work_area)
        websites.append(website)
        facebook_links.append(facebook)
        locations.append(location)

    # Create DataFrame
    df = pd.DataFrame(
        {
            "Name": names,
            "Work Areas": work_areas,
            "Website": websites,
            "Facebook": facebook_links,
            "Location": locations,
        }
    )

    return df


# Initialize an empty DataFrame to store all pages' data
all_data = pd.DataFrame()

# Loop through the pages
for page in range(1, 34):  # Pages 1 to 33
    url = base_url.format(page)
    print(f"Scraping page {page}...")
    page_data = scrape_page(url)
    all_data = pd.concat([all_data, page_data], ignore_index=True)

# Display and save the final combined data
print(all_data)
all_data.to_csv("malaysia_ngos_combined.csv", index=False)
