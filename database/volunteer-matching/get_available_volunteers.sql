-- =====================================================================
-- get_available_volunteers
-- Returns eligible volunteers for a given request (#289), matched by
-- help category, filtered by proximity for In-person requests, and
-- excluding volunteers already assigned to the request.
-- =====================================================================

DROP FUNCTION IF EXISTS get_available_volunteers(text, numeric);

CREATE OR REPLACE FUNCTION get_available_volunteers(
    p_request_id text,
    p_radius_km numeric DEFAULT 40   -- TODO: confirm matching radius with team; ~25 miles for now
)
RETURNS TABLE (
    volunteer_id text,
    full_name text,
    skills text[]
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_req_cat_id     varchar;
    v_req_type_id    integer;
    v_req_loc        varchar;
    v_req_lat        numeric;
    v_req_lng        numeric;
    v_is_in_person   boolean;
BEGIN
    -- Step 1: validate input
    IF p_request_id IS NULL OR btrim(p_request_id) = '' THEN
        RAISE EXCEPTION 'request_id is required' USING ERRCODE = '22023';
    END IF;

    -- Step 2: retrieve request details
    SELECT r.req_cat_id, r.req_type_id, r.req_loc
      INTO v_req_cat_id, v_req_type_id, v_req_loc
      FROM request r WHERE r.req_id = p_request_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'request_id % not found', p_request_id USING ERRCODE = 'P0002';
    END IF;

    SELECT (rt.req_type ILIKE '%person%') INTO v_is_in_person
      FROM request_type rt WHERE rt.req_type_id = v_req_type_id;

    -- TODO: req_loc is currently free-text; this assumes "lat,lng" format.
    -- Needs alignment with how requests actually populate this field.
    IF v_is_in_person AND v_req_loc IS NOT NULL AND v_req_loc LIKE '%,%' THEN
        v_req_lat := split_part(v_req_loc, ',', 1)::numeric;
        v_req_lng := split_part(v_req_loc, ',', 2)::numeric;
    END IF;

    RETURN QUERY
    WITH skill_matched AS (
        -- direct category match
        SELECT DISTINCT us.user_id FROM user_skills us WHERE us.cat_id = v_req_cat_id
        UNION
        -- also count volunteers skilled in the PARENT category, via
        -- help_categories_map (child_id = this request's category)
        SELECT DISTINCT us.user_id
          FROM user_skills us
          JOIN help_categories_map hcm ON hcm.parent_id = us.cat_id
         WHERE hcm.child_id = v_req_cat_id
    ),
    location_filtered AS (
        SELECT sm.user_id
          FROM skill_matched sm
          LEFT JOIN volunteer_locations vl ON vl.user_id = sm.user_id
         WHERE
            v_is_in_person IS DISTINCT FROM TRUE
            OR (
                vl.user_id IS NOT NULL
                AND v_req_lat IS NOT NULL
                AND (
                    6371 * acos(
                        LEAST(1, GREATEST(-1,
                            cos(radians(v_req_lat)) * cos(radians(vl.curr_lat)) *
                            cos(radians(vl.curr_lng) - radians(v_req_lng)) +
                            sin(radians(v_req_lat)) * sin(radians(vl.curr_lat))
                        ))
                    )
                ) <= p_radius_km
            )
    ),
    not_already_assigned AS (
        SELECT lf.user_id
          FROM location_filtered lf
         WHERE NOT EXISTS (
             SELECT 1 FROM volunteers_assigned va
              WHERE va.request_id = p_request_id AND va.volunteer_id = lf.user_id
         )
    )
    SELECT
        u.user_id::text,
        u.full_name::text,
        array_agg(DISTINCT us.cat_id)::text[] AS skills
      FROM not_already_assigned naa
      JOIN users u ON u.user_id = naa.user_id
      JOIN user_status ust ON ust.user_status_id = u.user_status_id
      JOIN user_skills us ON us.user_id = u.user_id
     WHERE ust.user_status = 'ACTIVE'
     GROUP BY u.user_id, u.full_name;
END;
$$;