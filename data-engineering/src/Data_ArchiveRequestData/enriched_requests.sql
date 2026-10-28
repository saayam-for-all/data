SELECT
    r.req_id,

    -- User references: no readable names exist in the supplied schema
    r.creator_id,
    r.beneficiary_id,
    r.lead_volunteer_id,

    -- Readable lookup values
    hc.cat_name AS category_name,
    rf.req_for AS request_for_name,
    ril.req_islead AS is_lead_volunteer,
    rt.req_type AS request_type_name,
    rp.req_priority AS priority_name,
    rs.req_status AS status_name,

    -- Original request details
    r.req_subj,
    r.req_desc,
    r.req_doc_link,
    r.audio_req_desc,
    r.deletion_reason,

    -- Convert geometry to CSV-friendly text
    ST_AsText(r.req_loc) AS req_loc,
    ST_AsText(r.created_loc) AS created_loc,

    r.iscalamity,
    r.to_public,
    r.submission_date,
    r.serviced_date,
    r.last_updated_at

FROM virginia_dev_saayam_rdbms.requests AS r

LEFT JOIN virginia_dev_saayam_rdbms.users AS creator
    ON r.creator_id = creator.user_id

LEFT JOIN virginia_dev_saayam_rdbms.users AS beneficiary
    ON r.beneficiary_id = beneficiary.user_id

LEFT JOIN virginia_dev_saayam_rdbms.users AS volunteer
    ON r.lead_volunteer_id = volunteer.user_id

LEFT JOIN virginia_dev_saayam_rdbms.help_categories AS hc
    ON r.req_cat_id = hc.cat_id

LEFT JOIN virginia_dev_saayam_rdbms.request_for AS rf
    ON r.req_for_id = rf.req_for_id

LEFT JOIN virginia_dev_saayam_rdbms.request_isleadvol AS ril
    ON r.req_islead_id = ril.req_islead_id

LEFT JOIN virginia_dev_saayam_rdbms.request_types AS rt
    ON r.req_type_id = rt.req_type_id

LEFT JOIN virginia_dev_saayam_rdbms.request_priorities AS rp
    ON r.req_priority_id = rp.req_priority_id

LEFT JOIN virginia_dev_saayam_rdbms.request_statuses AS rs
    ON r.req_status_id = rs.req_status_id

WHERE r.last_updated_at > %(previous_watermark)s
  AND r.last_updated_at <= %(current_watermark)s

ORDER BY r.req_id;