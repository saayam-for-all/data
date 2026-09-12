from __future__ import annotations


COUNTRIES_COLUMNS = [
    "country_id",
    "country_name",
    "phone_code",
    "country_code",
    "last_updated_at",
    "is_eu_member",
]


STATES_COLUMNS = [
    "state_id",
    "country_id",
    "state_name",
    "state_code",
    "last_updated_at",
]


CITIES_COLUMNS = [
    "city_id",
    "state_id",
    "city_name",
    "lattitude",
    "longitude",
    "last_updated_at",
]


USERS_COLUMNS = [
    "user_id",
    "state_id",
    "country_id",
    "user_status_id",
    "full_name",
    "first_name",
    "middle_name",
    "last_name",
    "primary_email_address",
    "primary_phone_number",
    "addr_ln1",
    "addr_ln2",
    "addr_ln3",
    "city_name",
    "zip_code",
    "last_location",
    "last_updated_at",
    "time_zone",
    "profile_picture_path",
    "gender",
    "language_1",
    "language_2",
    "language_3",
    "promotion_wizard_stage",
    "promotion_wizard_last_updated_at",
    "external_auth_provider",
    "dob",
    "is_eu",
]


VOLUNTEER_DETAILS_COLUMNS = [
    "user_id",
    "terms_and_conditions",
    "terms_accepted_at",
    "govt_id_path1",
    "govt_id_path2",
    "path1_updated_at",
    "path2_updated_at",
    "availability_days",
    "availability_times",
    "created_at",
    "last_updated_at",
]


USER_SKILLS_COLUMNS = [
    "user_id",
    "cat_id",
    "skill_level",
    "created_at",
    "last_updated_at",
]


VOLUNTEER_LOCATIONS_COLUMNS = [
    "user_id",
    "prev_loc",
    "curr_loc",
    "last_updated_at",
]


USER_LOCATIONS_COLUMNS = [
    "user_id",
    "prev_loc",
    "curr_loc",
    "last_updated_at",
]


HELP_CATEGORIES_COLUMNS = [
    "cat_id",
    "cat_name",
    "cat_desc",
    "last_updated_at",
]


ORGANIZATIONS_COLUMNS = [
    "org_id",
    "org_name",
    "street",
    "city_name",
    "state_id",
    "zip_code",
    "mission",
    "web_url",
    "phone",
    "email",
    "org_type",
    "org_size",
    "org_rating",
    "is_collaborator",
    "is_contributor",
    "created_at",
    "last_updated_at",
]


TABLE_COLUMNS = {
    "countries": COUNTRIES_COLUMNS,
    "states": STATES_COLUMNS,
    "cities": CITIES_COLUMNS,
    "users": USERS_COLUMNS,
    "volunteer_details": VOLUNTEER_DETAILS_COLUMNS,
    "user_skills": USER_SKILLS_COLUMNS,
    "volunteer_locations": VOLUNTEER_LOCATIONS_COLUMNS,
    "user_locations": USER_LOCATIONS_COLUMNS,
    "help_categories": HELP_CATEGORIES_COLUMNS,
    "organizations": ORGANIZATIONS_COLUMNS,
}


CSV_FILE_NAMES = {
    table_name: f"{table_name}.csv"
    for table_name in TABLE_COLUMNS
}


SKILL_LEVELS = {
    "BEGINNER",
    "INTERMEDIATE",
    "ADVANCED",
    "EXPERT",
}


ORGANIZATION_TYPES = {
    "non_profit",
    "for_profit",
}


ORGANIZATION_SIZES = {
    "small",
    "medium",
    "large",
}