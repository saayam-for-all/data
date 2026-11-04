SELECT r."req_id", CASE WHEN r."creator_id" IS NULL THEN NULL
            WHEN "l0"."user_id" IS NULL THEN '[UNMATCHED: ' || CAST(r."creator_id" AS text) || ']'
            WHEN "l0"."full_name" IS NULL OR trim(CAST("l0"."full_name" AS text)) = ''
                THEN '[MISSING LABEL: ' || CAST(r."creator_id" AS text) || ']'
            ELSE CAST("l0"."full_name" AS text) END AS "creator_name", CASE WHEN r."req_for_id" IS NULL THEN NULL
            WHEN "l3"."req_for_id" IS NULL THEN '[UNMATCHED: ' || CAST(r."req_for_id" AS text) || ']'
            WHEN "l3"."req_for" IS NULL OR trim(CAST("l3"."req_for" AS text)) = ''
                THEN '[MISSING LABEL: ' || CAST(r."req_for_id" AS text) || ']'
            ELSE CAST("l3"."req_for" AS text) END AS "request_for", CASE WHEN r."req_islead_id" IS NULL THEN NULL
            WHEN "l4"."req_islead_id" IS NULL THEN '[UNMATCHED: ' || CAST(r."req_islead_id" AS text) || ']'
            WHEN "l4"."req_islead" IS NULL OR trim(CAST("l4"."req_islead" AS text)) = ''
                THEN '[MISSING LABEL: ' || CAST(r."req_islead_id" AS text) || ']'
            ELSE CAST("l4"."req_islead" AS text) END AS "request_is_lead_volunteer", CASE WHEN r."req_cat_id" IS NULL THEN NULL
            WHEN "l5"."cat_id" IS NULL THEN '[UNMATCHED: ' || CAST(r."req_cat_id" AS text) || ']'
            WHEN "l5"."cat_name" IS NULL OR trim(CAST("l5"."cat_name" AS text)) = ''
                THEN '[MISSING LABEL: ' || CAST(r."req_cat_id" AS text) || ']'
            ELSE CAST("l5"."cat_name" AS text) END AS "help_category", CASE WHEN r."req_type_id" IS NULL THEN NULL
            WHEN "l6"."req_type_id" IS NULL THEN '[UNMATCHED: ' || CAST(r."req_type_id" AS text) || ']'
            WHEN "l6"."req_type" IS NULL OR trim(CAST("l6"."req_type" AS text)) = ''
                THEN '[MISSING LABEL: ' || CAST(r."req_type_id" AS text) || ']'
            ELSE CAST("l6"."req_type" AS text) END AS "request_type", CASE WHEN r."req_priority_id" IS NULL THEN NULL
            WHEN "l7"."req_priority_id" IS NULL THEN '[UNMATCHED: ' || CAST(r."req_priority_id" AS text) || ']'
            WHEN "l7"."req_priority" IS NULL OR trim(CAST("l7"."req_priority" AS text)) = ''
                THEN '[MISSING LABEL: ' || CAST(r."req_priority_id" AS text) || ']'
            ELSE CAST("l7"."req_priority" AS text) END AS "request_priority", CASE WHEN r."req_status_id" IS NULL THEN NULL
            WHEN "l8"."req_status_id" IS NULL THEN '[UNMATCHED: ' || CAST(r."req_status_id" AS text) || ']'
            WHEN "l8"."req_status" IS NULL OR trim(CAST("l8"."req_status" AS text)) = ''
                THEN '[MISSING LABEL: ' || CAST(r."req_status_id" AS text) || ']'
            ELSE CAST("l8"."req_status" AS text) END AS "request_status", r."req_loc", r."iscalamity", r."req_subj", r."req_desc", r."req_doc_link", r."audio_req_desc", r."submission_date", r."serviced_date", r."last_updated_at", r."to_public", CASE WHEN r."beneficiary_id" IS NULL THEN NULL
            WHEN "l1"."user_id" IS NULL THEN '[UNMATCHED: ' || CAST(r."beneficiary_id" AS text) || ']'
            WHEN "l1"."full_name" IS NULL OR trim(CAST("l1"."full_name" AS text)) = ''
                THEN '[MISSING LABEL: ' || CAST(r."beneficiary_id" AS text) || ']'
            ELSE CAST("l1"."full_name" AS text) END AS "beneficiary_name", CASE WHEN r."lead_volunteer_id" IS NULL THEN NULL
            WHEN "l2"."user_id" IS NULL THEN '[UNMATCHED: ' || CAST(r."lead_volunteer_id" AS text) || ']'
            WHEN "l2"."full_name" IS NULL OR trim(CAST("l2"."full_name" AS text)) = ''
                THEN '[MISSING LABEL: ' || CAST(r."lead_volunteer_id" AS text) || ']'
            ELSE CAST("l2"."full_name" AS text) END AS "lead_volunteer_name", r."deletion_reason", r."creator_id" IS NULL, r."creator_id" IS NOT NULL AND "l0"."user_id" IS NULL, "l0"."user_id" IS NOT NULL AND ("l0"."full_name" IS NULL OR trim(CAST("l0"."full_name" AS text)) = ''), r."beneficiary_id" IS NULL, r."beneficiary_id" IS NOT NULL AND "l1"."user_id" IS NULL, "l1"."user_id" IS NOT NULL AND ("l1"."full_name" IS NULL OR trim(CAST("l1"."full_name" AS text)) = ''), r."lead_volunteer_id" IS NULL, r."lead_volunteer_id" IS NOT NULL AND "l2"."user_id" IS NULL, "l2"."user_id" IS NOT NULL AND ("l2"."full_name" IS NULL OR trim(CAST("l2"."full_name" AS text)) = ''), r."req_for_id" IS NULL, r."req_for_id" IS NOT NULL AND "l3"."req_for_id" IS NULL, "l3"."req_for_id" IS NOT NULL AND ("l3"."req_for" IS NULL OR trim(CAST("l3"."req_for" AS text)) = ''), r."req_islead_id" IS NULL, r."req_islead_id" IS NOT NULL AND "l4"."req_islead_id" IS NULL, "l4"."req_islead_id" IS NOT NULL AND ("l4"."req_islead" IS NULL OR trim(CAST("l4"."req_islead" AS text)) = ''), r."req_cat_id" IS NULL, r."req_cat_id" IS NOT NULL AND "l5"."cat_id" IS NULL, "l5"."cat_id" IS NOT NULL AND ("l5"."cat_name" IS NULL OR trim(CAST("l5"."cat_name" AS text)) = ''), r."req_type_id" IS NULL, r."req_type_id" IS NOT NULL AND "l6"."req_type_id" IS NULL, "l6"."req_type_id" IS NOT NULL AND ("l6"."req_type" IS NULL OR trim(CAST("l6"."req_type" AS text)) = ''), r."req_priority_id" IS NULL, r."req_priority_id" IS NOT NULL AND "l7"."req_priority_id" IS NULL, "l7"."req_priority_id" IS NOT NULL AND ("l7"."req_priority" IS NULL OR trim(CAST("l7"."req_priority" AS text)) = ''), r."req_status_id" IS NULL, r."req_status_id" IS NOT NULL AND "l8"."req_status_id" IS NULL, "l8"."req_status_id" IS NOT NULL AND ("l8"."req_status" IS NULL OR trim(CAST("l8"."req_status" AS text)) = '') FROM "archive_demo_1f7e49c85e5e43e4a2267e14908263bb"."requests" AS r LEFT JOIN "archive_demo_1f7e49c85e5e43e4a2267e14908263bb"."users" AS "l0" ON r."creator_id" = "l0"."user_id" LEFT JOIN "archive_demo_1f7e49c85e5e43e4a2267e14908263bb"."users" AS "l1" ON r."beneficiary_id" = "l1"."user_id" LEFT JOIN "archive_demo_1f7e49c85e5e43e4a2267e14908263bb"."users" AS "l2" ON r."lead_volunteer_id" = "l2"."user_id" LEFT JOIN "archive_demo_1f7e49c85e5e43e4a2267e14908263bb"."request_for" AS "l3" ON r."req_for_id" = "l3"."req_for_id" LEFT JOIN "archive_demo_1f7e49c85e5e43e4a2267e14908263bb"."request_isleadvol" AS "l4" ON r."req_islead_id" = "l4"."req_islead_id" LEFT JOIN "archive_demo_1f7e49c85e5e43e4a2267e14908263bb"."help_category" AS "l5" ON r."req_cat_id" = "l5"."cat_id" LEFT JOIN "archive_demo_1f7e49c85e5e43e4a2267e14908263bb"."request_type" AS "l6" ON r."req_type_id" = "l6"."req_type_id" LEFT JOIN "archive_demo_1f7e49c85e5e43e4a2267e14908263bb"."request_priority" AS "l7" ON r."req_priority_id" = "l7"."req_priority_id" LEFT JOIN "archive_demo_1f7e49c85e5e43e4a2267e14908263bb"."request_statuses" AS "l8" ON r."req_status_id" = "l8"."req_status_id" WHERE r."serviced_date" < %s ORDER BY r."req_id";
