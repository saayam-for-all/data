-- Local-only lookup seed. Adapted from data commit
-- a9a14a18aaac012f425b946ae4639e0535f7efce:
-- database/lookup_tables/supporting_languages.csv and user_status.csv.
-- Current schema renames iso_639_1_code -> iso_code and last_update_date -> last_updated_at.
INSERT INTO virginia_dev_saayam_rdbms.supporting_languages
(language_id, language_name, iso_code, locale_code, writing_direction, total_speakers_m, is_active)
VALUES
(1,'English','en','en_US','LTR',1515.0,TRUE),
(2,'Mandarin Chinese','zh','zh_CN','LTR',1140.0,TRUE),
(3,'Hindi','hi','hi_IN','LTR',609.0,TRUE),
(4,'Spanish','es','es_ES','LTR',560.0,TRUE),
(5,'French','fr','fr_FR','LTR',312.0,TRUE),
(6,'Arabic','ar','ar_SA','RTL',280.0,TRUE),
(7,'Bengali','bn','bn_BD','LTR',278.0,TRUE),
(8,'Portuguese','pt','pt_PT','LTR',264.0,TRUE),
(9,'Russian','ru','ru_RU','LTR',255.0,TRUE),
(10,'Urdu','ur','ur_PK','RTL',230.0,TRUE),
(11,'German','de','de_DE','LTR',134.0,TRUE),
(12,'Telugu','te','te_IN','LTR',96.0,TRUE)
ON CONFLICT (language_id) DO NOTHING;

INSERT INTO virginia_dev_saayam_rdbms.user_status
(user_status_id, user_status, user_status_desc)
VALUES (1,'ACTIVE',NULL)
ON CONFLICT (user_status_id) DO NOTHING;

-- Fail instead of silently trusting a conflicting existing lookup mapping.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM (VALUES
          (1,'en','en_US'),(2,'zh','zh_CN'),(3,'hi','hi_IN'),
          (4,'es','es_ES'),(5,'fr','fr_FR'),(6,'ar','ar_SA'),
          (7,'bn','bn_BD'),(8,'pt','pt_PT'),(9,'ru','ru_RU'),
          (10,'ur','ur_PK'),(11,'de','de_DE'),(12,'te','te_IN')
        ) AS expected(id,iso,locale)
        LEFT JOIN virginia_dev_saayam_rdbms.supporting_languages AS actual
          ON actual.language_id=expected.id
        WHERE actual.iso_code IS DISTINCT FROM expected.iso
           OR actual.locale_code IS DISTINCT FROM expected.locale
    ) THEN
        RAISE EXCEPTION 'Existing language lookup IDs conflict with the pinned seed';
    END IF;
    IF (SELECT user_status FROM virginia_dev_saayam_rdbms.user_status
        WHERE user_status_id=1) IS DISTINCT FROM 'ACTIVE' THEN
        RAISE EXCEPTION 'Existing user_status_id=1 is not ACTIVE';
    END IF;
END $$;

