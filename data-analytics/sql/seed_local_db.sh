#!/usr/bin/env bash
# seed_local_db.sh
# Run this from inside the sql/ folder (where the CSVs live).
# Loads country, help_category, users, user_skills, volunteer_details
# into both virginia_dev_saayam_rdbms and ireland_dev_saayam_rdbms schemas.

set -e  # stop immediately if any command fails

CONTAINER=saayam-local
DB=saayam_local

# user_skills.csv has duplicate (user_id, cat_id) rows in the source data.
# Since that pair is the table's primary key, de-dupe once here (keeping the
# first occurrence of each pair) before loading into either schema.
echo "-- de-duplicating user_skills.csv (keeping first occurrence of each user_id+cat_id)"
awk -F',' 'NR==1{print; next} {key=$1","$2; if (!(key in seen)) {print; seen[key]=1}}' user_skills.csv > user_skills_dedup.csv
echo "   original rows: $(($(wc -l < user_skills.csv) - 1)), deduped rows: $(($(wc -l < user_skills_dedup.csv) - 1))"

# Some source CSVs use the literal text "NULL" to represent nulls, others
# use plain blank fields -- inconsistently, across different files. Rather
# than guess per-file, normalize all of them: any field that is literally
# "NULL" becomes a true empty field, so Postgres's default null handling
# (empty unquoted field = NULL) works uniformly for every load below.
echo "-- normalizing literal \"NULL\" text fields to true empty fields in all CSVs"
python clean_csv.py country.csv country_clean.csv
python clean_csv.py help_category.csv help_category_clean.csv
python clean_csv.py users.csv users_clean.csv
python clean_csv.py user_skills_dedup.csv user_skills_clean.csv
python clean_csv.py volunteer_details.csv volunteer_details_clean.csv
echo

for SCHEMA in virginia_dev_saayam_rdbms ireland_dev_saayam_rdbms; do
  echo "=== Seeding schema: $SCHEMA ==="

  echo "-- clearing existing rows (safe to re-run)"
  docker exec -i $CONTAINER psql -U postgres -d $DB \
    -c "TRUNCATE TABLE $SCHEMA.user_skills, $SCHEMA.volunteer_details, $SCHEMA.users, $SCHEMA.help_categories, $SCHEMA.country CASCADE;"

  echo "-- dropping FK constraints (sample CSVs aren't mutually consistent; not needed for our queries)"
  docker exec -i $CONTAINER psql -U postgres -d $DB \
    -c "ALTER TABLE $SCHEMA.volunteer_details DROP CONSTRAINT IF EXISTS fk_vd_user;
        ALTER TABLE $SCHEMA.user_skills DROP CONSTRAINT IF EXISTS fk_us_user;
        ALTER TABLE $SCHEMA.user_skills DROP CONSTRAINT IF EXISTS fk_us_cat;"

  echo "-- country"
  cat country_clean.csv | docker exec -i $CONTAINER psql -U postgres -d $DB \
    -c "\copy $SCHEMA.country (country_id, country_name, phone_code, country_code, last_update_date, is_eu_member) FROM STDIN WITH (FORMAT csv, HEADER true, FORCE_NULL(country_id, country_name, phone_code, country_code, last_update_date, is_eu_member))"

  echo "-- help_categories"
  cat help_category_clean.csv | docker exec -i $CONTAINER psql -U postgres -d $DB \
    -c "\copy $SCHEMA.help_categories (cat_id, cat_name, cat_desc) FROM STDIN WITH (FORMAT csv, HEADER true, FORCE_NULL(cat_id, cat_name, cat_desc))"

  echo "-- users"
  cat users_clean.csv | docker exec -i $CONTAINER psql -U postgres -d $DB \
    -c "\copy $SCHEMA.users (user_id, state_id, country_id, user_status_id, user_category_id, full_name, first_name, middle_name, last_name, primary_email_address, primary_phone_number, addr_ln1, addr_ln2, addr_ln3, city_name, zip_code, last_location, last_update_date, time_zone, profile_picture_path, gender, language_1, language_2, language_3, promotion_wizard_stage, promotion_wizard_last_update_date, external_auth_provider, dob) FROM STDIN WITH (FORMAT csv, HEADER true, FORCE_NULL(user_id, state_id, country_id, user_status_id, user_category_id, full_name, first_name, middle_name, last_name, primary_email_address, primary_phone_number, addr_ln1, addr_ln2, addr_ln3, city_name, zip_code, last_location, last_update_date, time_zone, profile_picture_path, gender, language_1, language_2, language_3, promotion_wizard_stage, promotion_wizard_last_update_date, external_auth_provider, dob))"

  echo "-- user_skills"
  cat user_skills_clean.csv | docker exec -i $CONTAINER psql -U postgres -d $DB \
    -c "\copy $SCHEMA.user_skills (user_id, cat_id, created_date, last_update_date) FROM STDIN WITH (FORMAT csv, HEADER true, FORCE_NULL(user_id, cat_id, created_date, last_update_date))"

  echo "-- volunteer_details"
  cat volunteer_details_clean.csv | docker exec -i $CONTAINER psql -U postgres -d $DB \
    -c "\copy $SCHEMA.volunteer_details (user_id, terms_and_conditions, terms_accepted_at, govt_id_path1, govt_id_path2, path1_updated_at, path2_updated_at, availability_days, availability_times, created_at, last_updated_at) FROM STDIN WITH (FORMAT csv, HEADER true, FORCE_NULL(user_id, terms_and_conditions, terms_accepted_at, govt_id_path1, govt_id_path2, path1_updated_at, path2_updated_at, availability_days, availability_times, created_at, last_updated_at))"

  echo "=== Done with $SCHEMA ==="
  echo
done

echo "All schemas seeded successfully."
