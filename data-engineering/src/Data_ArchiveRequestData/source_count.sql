SELECT COUNT(*) AS source_count
FROM virginia_dev_saayam_rdbms.requests
WHERE last_updated_at > %(previous_watermark)s
  AND last_updated_at <= %(current_watermark)s;