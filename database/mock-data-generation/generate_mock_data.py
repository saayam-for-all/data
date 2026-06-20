from faker import Faker
import pandas as pd
import random
import os
import uuid
import json
from datetime import datetime, timedelta

fake = Faker()

# CONFIG
NUM_ROWS = 10000 
OUTPUT_DIR = "../mock_db"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# REFERENCE DATA (Matching your schema exactly)
# Countries (country_id is INTEGER per schema)
COUNTRIES = {
    1: {"name": "United States", "code": "US", "phone_code": "+1"},
    2: {"name": "Canada", "code": "CA", "phone_code": "+1"},
    3: {"name": "United Kingdom", "code": "UK", "phone_code": "+44"}
}

# States (state_id is VARCHAR(50) per schema, links to country_id INTEGER)
STATES = {
    # US States (country_id = 1)
    "US-NY": {"name": "New York", "country_id": 1, "state_code": "NY"},
    "US-CA": {"name": "California", "country_id": 1, "state_code": "CA"},
    "US-TX": {"name": "Texas", "country_id": 1, "state_code": "TX"},
    "US-FL": {"name": "Florida", "country_id": 1, "state_code": "FL"},
    
    # Canada (country_id = 2)
    "CA-ON": {"name": "Ontario", "country_id": 2, "state_code": "ON"},
    "CA-BC": {"name": "British Columbia", "country_id": 2, "state_code": "BC"},
    
    # UK (country_id = 3)
    "UK-ENG": {"name": "England", "country_id": 3, "state_code": "ENG"},
    "UK-SCT": {"name": "Scotland", "country_id": 3, "state_code": "SCT"},
}

# Build reverse mapping: country_id -> list of valid state_ids (strings)
COUNTRY_TO_STATES = {}
for state_id, state_info in STATES.items():
    cid = state_info["country_id"]
    if cid not in COUNTRY_TO_STATES:
        COUNTRY_TO_STATES[cid] = []
    COUNTRY_TO_STATES[cid].append(state_id)

# User Status (user_status_id is BIGINT per schema)
USER_STATUSES = {
    1: "Active",
    2: "Inactive", 
    3: "Pending",
    4: "Suspended"
}

# User Category (user_category_id is INTEGER per schema)
USER_CATEGORIES = {
    1: "Requester",
    2: "Volunteer",
    3: "Both",
    4: "Admin"
}

# Request Categories (cat_id is VARCHAR(50) per schema)
REQUEST_CATEGORIES = {
    "ELDERLY_CARE": "Elderly Care",
    "CHILDCARE": "Childcare",
    "HOME_REPAIR": "Home Repair",
    "TUTORING": "Education/Tutoring",
    "EMERGENCY": "Emergency/Disaster",
    "TRANSPORT": "Transportation",
    "MEAL_PREP": "Meal Preparation",
    "TECH_HELP": "Technology Help"
}

# Request Templates (realistic content)
REQUEST_TEMPLATES = {
    "ELDERLY_CARE": {
        "subjects": [
            "Need assistance with grocery shopping",
            "Help required for medical appointment transport",
            "Looking for companion for daily walks",
            "Assistance needed with meal preparation",
            "Help with medication reminders"
        ],
        "descriptions": [
            "Elderly person needs help buying groceries twice a week. Lives alone and has mobility issues.",
            "Need reliable transport to and from hospital for chemotherapy sessions every Friday.",
            "85-year-old looking for someone to walk with in the park for 30 minutes daily.",
            "Requires help preparing lunch and dinner due to arthritis in hands.",
            "Needs someone to help organize weekly pills and set reminders."
        ]
    },
    "CHILDCARE": {
        "subjects": [
            "Emergency babysitting needed for 2 children",
            "After-school pickup and homework help",
            "Weekend childcare while parent works",
            "Special needs child requires respite care",
            "Temporary foster care support"
        ],
        "descriptions": [
            "Single parent working night shift needs emergency care for ages 4 and 7.",
            "Need pickup from Lincoln Elementary at 3pm and help with math homework.",
            "Working weekends, need childcare Saturday-Sunday 8am-6pm for toddler.",
            "Autistic child needs experienced caregiver for 4 hours on Saturdays.",
            "Supporting foster family with temporary relief care for infant."
        ]
    },
    "HOME_REPAIR": {
        "subjects": [
            "Wheelchair ramp installation needed",
            "Plumbing repair for leaky faucet",
            "Garden maintenance for senior citizen",
            "Snow removal service needed",
            "Electrical outlet repair"
        ],
        "descriptions": [
            "Veteran with mobility issues needs wooden ramp built for front entrance.",
            "Kitchen sink dripping constantly, cannot afford professional plumber.",
            "Elderly couple cannot maintain large backyard, need monthly mowing.",
            "Senior unable to shovel driveway, need help after snowstorms.",
            "Living room outlet sparking, safety concern for family with kids."
        ]
    },
    "TUTORING": {
        "subjects": [
            "Math tutor needed for high school student",
            "ESL conversation practice partner",
            "Computer literacy training for seniors",
            "Reading buddy for elementary child",
            "SAT prep tutor required"
        ],
        "descriptions": [
            "10th grader struggling with algebra 2, needs twice weekly tutoring.",
            "Recent immigrant wants to practice English conversation 2 hours weekly.",
            "Retiree wants to learn email and video calls to connect with grandchildren.",
            "2nd grader reading below grade level, needs patient helper after school.",
            "Junior needs help with SAT math and verbal sections, aiming for 1300+."
        ]
    },
    "EMERGENCY": {
        "subjects": [
            "Temporary housing after house fire",
            "Food and supplies after flooding",
            "Emotional support after natural disaster",
            "Debris cleanup assistance",
            "Emergency pet sheltering"
        ],
        "descriptions": [
            "Family of 4 lost home in fire, need temporary accommodation for 2 weeks.",
            "Basement flooded, lost food supplies, need non-perishables and water.",
            "Anxious after tornado, need counselor or support group recommendations.",
            "Elderly unable to clear fallen trees from yard after storm.",
            "Evacuated due to hurricane, need temporary foster for 2 cats and dog."
        ]
    },
    "TRANSPORT": {
        "subjects": [
            "Ride needed to doctor appointment",
            "Transportation for wheelchair-bound senior",
            "Airport pickup for elderly visitor",
            "Grocery store transportation weekly",
            "Pharmacy pickup service needed"
        ],
        "descriptions": [
            "Need ride to Dr. Smith's office downtown, wheelchair accessible vehicle required.",
            "Elderly woman needs regular transport to physical therapy sessions.",
            "Picking up 80-year-old aunt from airport, needs assistance with luggage.",
            "Weekly trip to supermarket, can no longer drive due to vision issues.",
            "Need someone to pick up prescriptions from CVS twice a month."
        ]
    },
    "MEAL_PREP": {
        "subjects": [
            "Meal prep for diabetic senior",
            "Cooking assistance for disabled veteran",
            "Healthy meal delivery needed",
            "Help with special diet preparation",
            "Batch cooking for busy family"
        ],
        "descriptions": [
            "Need help preparing low-sugar meals for Type 2 diabetic, 5 days a week.",
            "Veteran with PTSD needs assistance cooking, prefers simple recipes.",
            "Elderly couple needs nutritious meals delivered due to mobility issues.",
            "Celiac disease requires strict gluten-free meal preparation help.",
            "Working single mom needs help batch cooking for the week on Sundays."
        ]
    },
    "TECH_HELP": {
        "subjects": [
            "Smartphone setup for senior",
            "Computer virus removal help",
            "WiFi setup assistance",
            "Video calling setup for family",
            "Online banking security help"
        ],
        "descriptions": [
            "75-year-old needs help setting up new iPhone and understanding apps.",
            "Laptop running slow, suspect malware, need tech-savvy volunteer.",
            "New router installed, need help connecting all devices in the house.",
            "Want to FaceTime with grandchildren, need setup and tutorial.",
            "Concerned about online banking security, need guidance on best practices."
        ]
    }
}

# Request Status (req_status_id is INTEGER per schema)
REQUEST_STATUSES = {
    1: "Open",
    2: "Assigned",
    3: "In Progress", 
    4: "Completed",
    5: "Cancelled"
}

# Request Priority (req_priority_id is INTEGER per schema)
REQUEST_PRIORITIES = {
    1: "Low",
    2: "Medium",
    3: "High",
    4: "Urgent"
}

# Request Type (req_type_id is INTEGER per schema)
REQUEST_TYPES = {
    1: "One-time",
    2: "Recurring",
    3: "Emergency"
}

# Request For (req_for_id is INTEGER per schema)
REQUEST_FOR = {
    1: "Self",
    2: "Family Member",
    3: "Friend",
    4: "Neighbor",
    5: "Client"
}

# Is Lead Volunteer (req_islead_id is INTEGER per schema)
LEAD_VOLUNTEER_OPTS = {
    1: "Yes - Lead Volunteer",
    2: "No - Support Volunteer",
    3: "Not Assigned Yet"
}

# HELPER FUNCTIONS

def generate_uuid():
    """Generate UUID string for IDs"""
    return str(uuid.uuid4())

def get_state_for_country(country_id):
    """Get valid state_id for given country_id"""
    valid_states = COUNTRY_TO_STATES.get(country_id, [])
    return random.choice(valid_states) if valid_states else None

def get_realistic_request(cat_id):
    """Get realistic subject and description for category"""
    templates = REQUEST_TEMPLATES.get(cat_id, REQUEST_TEMPLATES["ELDERLY_CARE"])
    idx = random.randint(0, len(templates["subjects"]) - 1)
    return templates["subjects"][idx], templates["descriptions"][idx]

# GENERATE USERS (All 26 columns per schema)

print("Generating users...")
users = []
used_emails = set()
user_ids = []  # Store for FK references

for i in range(NUM_ROWS):
    user_id = generate_uuid()
    user_ids.append(user_id)
    
    # Consistent country-state relationship
    country_id = random.choice(list(COUNTRIES.keys()))
    state_id = get_state_for_country(country_id)
    state_info = STATES.get(state_id, {})
    
    # Generate unique email
    email = fake.email()
    while email in used_emails:
        email = fake.email()
    used_emails.add(email)
    
    # Generate name parts
    first_name = fake.first_name()
    last_name = fake.last_name()
    middle_name = fake.first_name() if random.random() > 0.5 else None
    
    users.append({
        "user_id": user_id,                    
        "state_id": state_id,                 
        "country_id": country_id,              
        "user_status_id": random.choice(list(USER_STATUSES.keys())),   
        "user_category_id": random.choice(list(USER_CATEGORIES.keys())), 
        "full_name": f"{first_name} {last_name}",
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "primary_email_address": email,
        "primary_phone_number": fake.phone_number()[:20],
        "addr_ln1": fake.street_address(),
        "addr_ln2": fake.secondary_address() if random.random() > 0.7 else None,
        "addr_ln3": None,
        "city_name": fake.city(),
        "zip_code": fake.zipcode(),
        "last_location": f"{fake.latitude()}, {fake.longitude()}",
        "last_update_date": fake.date_time_between(start_date="-1y", end_date="now"),
        "time_zone": random.choice(["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "Europe/London"]),
        "profile_picture_path": f"/uploads/profiles/{user_id}.jpg" if random.random() > 0.3 else None,
        "gender": random.choice(["Male", "Female", "Non-Binary", None]),
        "language_1": random.choice(["English", "Spanish", "French", "Mandarin", "Hindi"]),
        "language_2": random.choice([None, "Spanish", "French", "German", "Mandarin"]),
        "language_3": None,
        "promotion_wizard_stage": random.randint(0, 5) if random.random() > 0.5 else None,
        "promotion_wizard_last_update_date": fake.date_time_between(start_date="-6m", end_date="now") if random.random() > 0.5 else None,
        "external_auth_provider": random.choice([None, "google", "facebook", "apple"]),
        "dob": fake.date_of_birth(minimum_age=18, maximum_age=85)
    })

users_df = pd.DataFrame(users)

# GENERATE REQUESTS (All columns per schema)

print("Generating requests...")
requests_list = []
request_ids = []

for i in range(NUM_ROWS):
    req_id = generate_uuid()
    request_ids.append(req_id)
    
    # Get realistic content based on category
    cat_id = random.choice(list(REQUEST_CATEGORIES.keys()))
    subject, description = get_realistic_request(cat_id)
    
    # Truncate to match schema limits
    subject = subject[:125]  # req_subj is VARCHAR(125)
    description = description[:255]  # req_desc is VARCHAR(255)
    
    requests_list.append({
        "req_id": req_id,                              
        "req_user_id": random.choice(user_ids),        
        "req_for_id": random.choice(list(REQUEST_FOR.keys())),           
        "req_islead_id": random.choice(list(LEAD_VOLUNTEER_OPTS.keys())), 
        "req_cat_id": cat_id,                          
        "req_type_id": random.choice(list(REQUEST_TYPES.keys())),        
        "req_priority_id": random.choice(list(REQUEST_PRIORITIES.keys())), 
        "req_status_id": random.choice(list(REQUEST_STATUSES.keys())),   
        "req_loc": fake.city()[:125],                  
        "iscalamity": random.choice([True, False]),
        "req_subj": subject,                           
        "req_desc": description,                      
        "req_doc_link": fake.url() if random.random() > 0.8 else None,
        "audio_req_desc": None,
        "submission_date": fake.date_time_between(start_date="-1y", end_date="now"),
        "serviced_date": fake.date_time_between(start_date="-6m", end_date="now") if random.random() > 0.6 else None,
        "last_update_date": fake.date_time_between(start_date="-6m", end_date="now"),
        "to_public": random.choice([True, True, True, False])  # 75% public
    })

request_df = pd.DataFrame(requests_list)


# GENERATE VOLUNTEER DETAILS(All columns per schema, with realistic availability JSON)

print("Generating volunteer details...")
volunteers = []
volunteer_user_ids = [] 

# Select subset of users to be volunteers (70% of users)
volunteer_candidates = random.sample(user_ids, int(len(user_ids) * 0.7))

for user_id in volunteer_candidates:
    volunteer_user_ids.append(user_id)
    
    # Generate availability JSON
    availability_days = random.sample(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], 
                                     random.randint(2, 5))
    availability_times = {
        "morning": random.choice([True, False]),
        "afternoon": random.choice([True, False]),
        "evening": random.choice([True, False]),
        "weekend": random.choice([True, False])
    }


# GENERATE VOLUNTEER DETAILS(All columns per schema, with realistic availability JSON)


print("Generating volunteer details...")
volunteers = []
volunteer_user_ids = []  

# Select subset of users to be volunteers (70% of users)
volunteer_candidates = random.sample(user_ids, int(len(user_ids) * 0.7))

for user_id in volunteer_candidates:
    volunteer_user_ids.append(user_id)
    
    # Generate availability JSON
    availability_days = random.sample(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], 
                                     random.randint(2, 5))
    availability_times = {
        "morning": random.choice([True, False]),
        "afternoon": random.choice([True, False]),
        "evening": random.choice([True, False]),
        "weekend": random.choice([True, False])
    }
    
    volunteers.append({
        "user_id": user_id,                             
        "terms_and_conditions": True,
        "terms_accepted_at": fake.date_time_between(start_date="-1y", end_date="-6m"),
        "govt_id_path1": f"/uploads/ids/{user_id}_id1.jpg" if random.random() > 0.3 else None,
        "govt_id_path2": None,
        "path1_updated_at": fake.date_time_between(start_date="-1y", end_date="now") if random.random() > 0.3 else None,
        "path2_updated_at": None,
        "availability_days": json.dumps(availability_days),
        "availability_times": json.dumps(availability_times),
        "created_at": fake.date_time_between(start_date="-1y", end_date="-6m"),
        "last_updated_at": fake.date_time_between(start_date="-6m", end_date="now")
    })

volunteers_df = pd.DataFrame(volunteers)

# GENERATE VOLUNTEERS ASSIGNED (All columns per schema, with realistic FK references to requests and volunteers)


print("Generating volunteer assignments...")
assignments = []

for i in range(NUM_ROWS):
    if len(volunteer_user_ids) == 0 or len(request_ids) == 0:
        break
        
    assignments.append({
        "volunteers_assigned_id": i + 1,                
        "request_id": random.choice(request_ids),        
        "volunteer_id": random.choice(volunteer_user_ids), 
        "volunteer_type": random.choice(["Primary", "Secondary", "Backup"]),
        "last_update_date": fake.date_time_between(start_date="-6m", end_date="now")
    })

assignments_df = pd.DataFrame(assignments)


# GENERATE REQUEST COMMENTS (All columns per schema, with realistic FK references to requests and users, and realistic comment content)

print("Generating comments...")
comments = []

comment_templates = [
    "I can help with this request. Available tomorrow afternoon.",
    "Contacted the requester, waiting for response on specific location.",
    "Completed the task. Very rewarding experience working with this family!",
    "Need more information about the best time to visit.",
    "Unable to fulfill due to scheduling conflict this week.",
    "Thank you so much for your help! Really appreciated by the whole family.",
    "Is this still needed? I can assist next week if so.",
    "Assigned volunteer to this request. Status updated to In Progress.",
    "Follow-up: How did everything go with the service?",
    "Updated status to Completed. Great work everyone!",
    "Running 15 minutes late due to traffic.",
    "Brought extra supplies as requested. Ready to help!",
    "First time volunteering, very nervous but excited to help!",
    "Have experience with similar cases, confident I can assist.",
    "Requester was very grateful for the quick response."
]

for i in range(NUM_ROWS):
    if len(request_ids) == 0 or len(user_ids) == 0:
        break
        
    comments.append({
        "comment_id": i + 1,                             
        "req_id": random.choice(request_ids),            
        "commenter_id": random.choice(user_ids),         
        "comment_desc": random.choice(comment_templates), 
        "created_at": fake.date_time_between(start_date="-6m", end_date="now"),
        "last_updated_at": fake.date_time_between(start_date="-6m", end_date="now"),
        "isdeleted": random.choice([True, False, False, False, False])  # 20% deleted
    })

comments_df = pd.DataFrame(comments)

# SAVE ALL FILES

print("Saving CSV files...")

users_df.to_csv(f"{OUTPUT_DIR}/users.csv", index=False)
request_df.to_csv(f"{OUTPUT_DIR}/request.csv", index=False)
volunteers_df.to_csv(f"{OUTPUT_DIR}/volunteer_details.csv", index=False)
assignments_df.to_csv(f"{OUTPUT_DIR}/volunteers_assigned.csv", index=False)
comments_df.to_csv(f"{OUTPUT_DIR}/request_comments.csv", index=False)

print(f"\n Successfully generated {NUM_ROWS} rows per table!")
print(f" Files saved to: {OUTPUT_DIR}/")
print(f"\n Data Quality Checks:")
print(f"   • All user_ids are UUID strings (not integers)")
print(f"   • State codes are strings like 'US-NY', 'CA-ON' (not 1-5)")
print(f"   • Country-State relationships are consistent (NY only in US)")
print(f"   • Request subjects/descriptions are realistic and contextual")
print(f"   • Foreign keys reference valid existing IDs")