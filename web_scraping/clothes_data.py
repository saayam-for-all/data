# Import libraries
from bs4 import BeautifulSoup
import pandas as pd
import requests
from word2number import w2n


# Get the max page number to scrape all the clothes charities 
headers = {'User-Agent': 'Mozilla/5.0'}
url = 'https://www.charitynavigator.org/search?q=clothes&sort=rating&page=1'

def get_max_page_num(url):
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")
    pagination_container = soup.find("ul", class_='tw-flex tw-align-center tw-justify-center tw-w-full tw-pt-6 tw-mb-10')
    page_numbers = []
    if pagination_container:
        page_numbers = [int(a.text.strip()) for a in pagination_container.find_all('a', role='button') if a.text.strip().isdigit()]
    else:
        print("Pagination container not found.")
    return page_numbers[-1]


# Scrape the cloth NGO name, location, rating, services
def scrape_ngo_clothes_data(url):
  response = requests.get(url, headers=headers)
  soup = BeautifulSoup(response.text, "html.parser")

  cloth_ngo_name, cloth_ngo_location, cloth_ngo_rating, cloth_ngo_meta_data = [], [], [], []
  for charity_block in soup.find_all('div', class_='base_SearchResult__S7f9J'):
    # Extract the charity name
    name_tag = charity_block.find('h2')
    name = name_tag.text.strip() if name_tag else 'N/A'
    # print("Charity Name:", name)
    cloth_ngo_name.append(name)

    # Extract location
    location_tag = charity_block.find('div', class_='tw-mb-0 tw-text-gray-700 tw-text-base')
    location = location_tag.text.strip() if location_tag else 'N/A'
    # print("Location:", location)
    cloth_ngo_location.append(location)
    
    # Extract rating
    rating_img = charity_block.find('img', alt='rating')
    rating = rating_img['src'].split('/')[-1].replace('.svg', '').replace('_', ' ') if rating_img else 'N/A'
    if rating == 'N/A':
      cloth_ngo_rating.append("N/A")
    else:
      cloth_ngo_rating.append(w2n.word_to_num(rating.split(" ")[0].lower()))

    # Extract Meta Data
    meta_data_tags = charity_block.find_all('a', class_='base_SearchResultTag__mVjvy')
    meta_data = [tag.text.strip() for tag in meta_data_tags] if meta_data_tags else []
    # print("Meta:", ', '.join(meta_data))
    cloth_ngo_meta_data.append(', '.join(meta_data))

  return cloth_ngo_name, cloth_ngo_location, cloth_ngo_rating, cloth_ngo_meta_data


def scrape_all_clothes_ngos(max_page_num):
  cloth_ngo_name, cloth_ngo_location, cloth_ngo_website, cloth_ngo_rating, cloth_ngo_meta_data = [], [], [], [], []
  for i in range(1,max_page_num+1):
    base_url = f"https://www.charitynavigator.org/search?q=clothes&sort=rating&page={i}"
    name, location, rating, meta_data = scrape_ngo_clothes_data(base_url)
    cloth_ngo_name.extend(name)
    cloth_ngo_location.extend(location)
    cloth_ngo_website.extend([base_url]*len(name))
    cloth_ngo_rating.extend(rating)
    cloth_ngo_meta_data.extend(meta_data)

  df = pd.DataFrame(
        {
            "NGO_name": cloth_ngo_name,
            "Location": cloth_ngo_location,
            "Website": cloth_ngo_website,
            "Rating": cloth_ngo_rating,
            "Meta_data": cloth_ngo_meta_data,
        }
    )
  return df


max_page_num = get_max_page_num(url)
print('Max Page Number:',max_page_num)
clothes_df = scrape_all_clothes_ngos(max_page_num)
# #print(clothes_df.head())
# print(clothes_df.tail())

clothes_df.to_csv('clothes_ngos.csv', index=False)