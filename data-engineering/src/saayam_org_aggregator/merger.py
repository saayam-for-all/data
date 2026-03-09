import pandas as pd


def merge_organizations(db_organizations: pd.DataFrame, genAI_organizations: pd.DataFrame) -> pd.DataFrame:
    """Merges DB and AI sources, pins collaborators to the top."""
    try:
        db_orgs = db_organizations.rename(columns={'org_name': 'name', 'city_name': 'location', 'phone': 'contact'})
        ai_orgs = genAI_organizations.rename(columns={'organization_name': 'name'})

        combined_df = pd.concat([db_orgs, ai_orgs], ignore_index=True)
        combined_df = combined_df.sort_values(by='is_collaborator', ascending=False).reset_index(drop=True)

        cols = ['name', 'location', 'contact', 'email', 'web_url', 'mission', 'source', 'org_type', 'is_collaborator', 'db_or_ai']
        return combined_df[[c for c in cols if c in combined_df.columns]]
    except Exception as e:
        raise Exception(f'Merge error: {str(e)}')