CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;
SET search_path TO virginia_dev_saayam_rdbms;

CREATE TABLE IF NOT EXISTS country (
    country_id INT PRIMARY KEY,
    country_name VARCHAR(100),
    country_code VARCHAR(6)
);
INSERT INTO country VALUES (1,'United States','US') ON CONFLICT DO NOTHING;

-- Named "states" (plural) per the new issue text.
CREATE TABLE IF NOT EXISTS states (
    state_id VARCHAR(50) PRIMARY KEY,
    country_id INT NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    state_code VARCHAR(6),
    last_update_date TIMESTAMP,
    FOREIGN KEY (country_id) REFERENCES country(country_id)
);

-- org_type / org_size / is_collaborator / is_contributor kept as free-form
-- text/boolean (not enums) since real sample data uses mixed-case strings
-- like "Non-Profit" / "For-profit" rather than the enum-style values.
CREATE TABLE IF NOT EXISTS organizations (
  org_id VARCHAR(255) PRIMARY KEY,
  org_name VARCHAR(125) NOT NULL,
  street VARCHAR(255),
  city_name VARCHAR(100),
  state_id VARCHAR(50),
  zip_code VARCHAR(10),
  mission TEXT,
  web_url VARCHAR(255),
  phone VARCHAR(20),
  email VARCHAR(255),
  org_type VARCHAR(50),
  org_size VARCHAR(50),
  org_rating INTEGER CHECK (org_rating IS NULL OR (org_rating >= 1 AND org_rating <= 5)),
  is_collaborator BOOLEAN,
  is_contributor BOOLEAN,
  created_at TIMESTAMP WITHOUT TIME ZONE,
  last_updated_at TIMESTAMP WITHOUT TIME ZONE,
  FOREIGN KEY (state_id) REFERENCES states(state_id) ON DELETE SET NULL
);
