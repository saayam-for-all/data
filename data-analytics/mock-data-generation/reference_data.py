from __future__ import annotations


COUNTRIES = [
    {
        "country_id": 1,
        "country_name": "United States",
        "phone_code": "+1",
        "country_code": "US",
        "is_eu_member": False,
    },
    {
        "country_id": 2,
        "country_name": "Canada",
        "phone_code": "+1",
        "country_code": "CA",
        "is_eu_member": False,
    },
    {
        "country_id": 3,
        "country_name": "India",
        "phone_code": "+91",
        "country_code": "IN",
        "is_eu_member": False,
    },
    {
        "country_id": 4,
        "country_name": "Ireland",
        "phone_code": "+353",
        "country_code": "IE",
        "is_eu_member": True,
    },
    {
        "country_id": 5,
        "country_name": "Germany",
        "phone_code": "+49",
        "country_code": "DE",
        "is_eu_member": True,
    },
    {
        "country_id": 6,
        "country_name": "France",
        "phone_code": "+33",
        "country_code": "FR",
        "is_eu_member": True,
    },
    {
        "country_id": 7,
        "country_name": "United Kingdom",
        "phone_code": "+44",
        "country_code": "GB",
        "is_eu_member": False,
    },
    {
        "country_id": 8,
        "country_name": "Australia",
        "phone_code": "+61",
        "country_code": "AU",
        "is_eu_member": False,
    },
    {
        "country_id": 9,
        "country_name": "Singapore",
        "phone_code": "+65",
        "country_code": "SG",
        "is_eu_member": False,
    },
    {
        "country_id": 10,
        "country_name": "Japan",
        "phone_code": "+81",
        "country_code": "JP",
        "is_eu_member": False,
    },
]


US_STATES = [
    {
        "state_id": "VA",
        "country_id": 1,
        "state_name": "Virginia",
        "state_code": "VA",
        "latitude": 37.4316,
        "longitude": -78.6569,
        "time_zone": "America/New_York",
        "zip_prefix": "23",
    },
    {
        "state_id": "CA",
        "country_id": 1,
        "state_name": "California",
        "state_code": "CA",
        "latitude": 36.7783,
        "longitude": -119.4179,
        "time_zone": "America/Los_Angeles",
        "zip_prefix": "94",
    },
    {
        "state_id": "NY",
        "country_id": 1,
        "state_name": "New York",
        "state_code": "NY",
        "latitude": 42.9538,
        "longitude": -75.5268,
        "time_zone": "America/New_York",
        "zip_prefix": "10",
    },
    {
        "state_id": "TX",
        "country_id": 1,
        "state_name": "Texas",
        "state_code": "TX",
        "latitude": 31.9686,
        "longitude": -99.9018,
        "time_zone": "America/Chicago",
        "zip_prefix": "75",
    },
    {
        "state_id": "NC",
        "country_id": 1,
        "state_name": "North Carolina",
        "state_code": "NC",
        "latitude": 35.7596,
        "longitude": -79.0193,
        "time_zone": "America/New_York",
        "zip_prefix": "27",
    },
    {
        "state_id": "IL",
        "country_id": 1,
        "state_name": "Illinois",
        "state_code": "IL",
        "latitude": 40.6331,
        "longitude": -89.3985,
        "time_zone": "America/Chicago",
        "zip_prefix": "60",
    },
    {
        "state_id": "MA",
        "country_id": 1,
        "state_name": "Massachusetts",
        "state_code": "MA",
        "latitude": 42.4072,
        "longitude": -71.3824,
        "time_zone": "America/New_York",
        "zip_prefix": "02",
    },
    {
        "state_id": "WA",
        "country_id": 1,
        "state_name": "Washington",
        "state_code": "WA",
        "latitude": 47.4009,
        "longitude": -120.7401,
        "time_zone": "America/Los_Angeles",
        "zip_prefix": "98",
    },
    {
        "state_id": "CO",
        "country_id": 1,
        "state_name": "Colorado",
        "state_code": "CO",
        "latitude": 39.5501,
        "longitude": -105.7821,
        "time_zone": "America/Denver",
        "zip_prefix": "80",
    },
    {
        "state_id": "FL",
        "country_id": 1,
        "state_name": "Florida",
        "state_code": "FL",
        "latitude": 27.6648,
        "longitude": -81.5158,
        "time_zone": "America/New_York",
        "zip_prefix": "33",
    },
]


CITY_NAME_WORDS = [
    "Cedar",
    "Maple",
    "Willow",
    "Oak",
    "Pine",
    "River",
    "Lake",
    "Meadow",
    "Summit",
    "Valley",
    "Spring",
    "Hill",
    "Forest",
    "Brook",
    "Stone",
    "Green",
    "Silver",
    "Golden",
    "Clear",
    "Fair",
]


CITY_NAME_SUFFIXES = [
    "Point",
    "Grove",
    "Heights",
    "Crossing",
    "Village",
    "Park",
    "Landing",
    "Haven",
    "Ridge",
    "Center",
]


HELP_CATEGORIES = [
    {
        "cat_id": "1",
        "cat_name": "FOOD_ASSISTANCE",
        "cat_desc": "Help with food access, meals, or essential groceries.",
    },
    {
        "cat_id": "2",
        "cat_name": "SHELTER_ASSISTANCE",
        "cat_desc": "Help locating temporary shelter or housing resources.",
    },
    {
        "cat_id": "3",
        "cat_name": "CLOTHING_ASSISTANCE",
        "cat_desc": "Help obtaining clothing and basic personal necessities.",
    },
    {
        "cat_id": "4",
        "cat_name": "TRANSPORTATION_ASSISTANCE",
        "cat_desc": "Help with transportation to essential destinations.",
    },
    {
        "cat_id": "5",
        "cat_name": "EDUCATION_SUPPORT",
        "cat_desc": "Tutoring, learning support, and educational assistance.",
    },
    {
        "cat_id": "6",
        "cat_name": "TECHNOLOGY_SUPPORT",
        "cat_desc": "Help with devices, software, or basic technology access.",
    },
    {
        "cat_id": "7",
        "cat_name": "ELDER_SUPPORT",
        "cat_desc": "Non-emergency assistance for elderly community members.",
    },
    {
        "cat_id": "8",
        "cat_name": "CHILDCARE_SUPPORT",
        "cat_desc": "Community assistance related to childcare needs.",
    },
    {
        "cat_id": "9",
        "cat_name": "MEDICAL_TRANSPORT",
        "cat_desc": "Non-emergency transportation related to medical care.",
    },
    {
        "cat_id": "10",
        "cat_name": "MENTAL_WELLNESS_SUPPORT",
        "cat_desc": "Non-emergency community mental wellness support.",
    },
    {
        "cat_id": "11",
        "cat_name": "JOB_SEARCH_SUPPORT",
        "cat_desc": "Help with resumes, job searches, and employment resources.",
    },
    {
        "cat_id": "12",
        "cat_name": "LANGUAGE_SUPPORT",
        "cat_desc": "Translation and language assistance for community needs.",
    },
    {
        "cat_id": "13",
        "cat_name": "LEGAL_RESOURCE_GUIDANCE",
        "cat_desc": "Help locating appropriate non-emergency legal resources.",
    },
    {
        "cat_id": "14",
        "cat_name": "HOME_REPAIR_SUPPORT",
        "cat_desc": "Basic community assistance with minor home repair needs.",
    },
    {
        "cat_id": "15",
        "cat_name": "DISASTER_RECOVERY_SUPPORT",
        "cat_desc": "Community assistance related to disaster recovery.",
    },
    {
        "cat_id": "16",
        "cat_name": "PET_SUPPORT",
        "cat_desc": "Help related to non-emergency pet care or supplies.",
    },
    {
        "cat_id": "17",
        "cat_name": "DOCUMENTATION_SUPPORT",
        "cat_desc": "Help understanding or organizing general documentation.",
    },
    {
        "cat_id": "18",
        "cat_name": "COMMUNITY_OUTREACH",
        "cat_desc": "Support for community outreach and volunteer engagement.",
    },
    {
        "cat_id": "19",
        "cat_name": "DONATION_PICKUP",
        "cat_desc": "Help coordinating pickup and movement of donated items.",
    },
    {
        "cat_id": "20",
        "cat_name": "OTHER_COMMUNITY_SUPPORT",
        "cat_desc": "Other non-emergency community assistance.",
    },
]


AVAILABILITY_DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


AVAILABILITY_WINDOWS = [
    {"start": "08:00", "end": "11:00"},
    {"start": "09:00", "end": "12:00"},
    {"start": "12:00", "end": "15:00"},
    {"start": "14:00", "end": "17:00"},
    {"start": "17:00", "end": "20:00"},
]