import pandas as pd
import json
from src.saayam_org_aggregator.merger import merge_organizations

def test_collaborator_sorting():
    print("--- 🧪 Running Collaborator Sorting Test ---")

    # 1. Mock Database Data (Contains one verified collaborator)
    db_data = pd.DataFrame([
        {
            "org_name": "Trusted Partner NGO", 
            "city_name": "New York",
            "phone": "123-456", 
            "email": "contact@trusted.org",
            "web_url": "https://trusted.org",
            "mission": "Education",
            "source": "Saayam DB",
            "org_type": "non_profit",
            "is_collaborator": True,  
            "db_or_ai": "db"
        },
        {
            "org_name": "Standard Local Org", 
            "city_name": "New York", 
            "phone": "999-000", 
            "email": "info@local.org",
            "web_url": "https://local.org",
            "mission": "Education",
            "source": "Saayam DB",
            "org_type": "non_profit",
            "is_collaborator": False,
            "db_or_ai": "db"
        }
    ])

    # 2. Mock AI Data (Should all be flagged as False for collaborator)
    ai_data = pd.DataFrame([
        {
            "organization_name": "AI Suggested School",
            "location": "New York",
            "contact": "Unknown",
            "email": "N/A",
            "web_url": "https://ai-school.com",
            "mission": "Education",
            "source": "GenAI",
            "org_type": "non_profit",
            "is_collaborator": False,
            "db_or_ai": "ai"
        }
    ])

    print("Merging data sources...")
    try:
        # Call your actual merge function from helpers.py
        result_df = merge_organizations(db_data, ai_data)

        # 3. Verify the Results
        print("\nFinal Result (JSON):")
        print(json.dumps(result_df.to_dict(orient='records'), indent=2))

        # Check if the first record is the collaborator
        if result_df.iloc[0]['is_collaborator'] == True:
            print("\n✅ PASS: Collaborator is at the top of the list.")
        else:
            print("\n❌ FAIL: Collaborator is NOT at the top.")

        # Check for new columns
        if 'org_type' in result_df.columns and 'is_collaborator' in result_df.columns:
            print("✅ PASS: New columns 'org_type' and 'is_collaborator' are present.")
        else:
            print("❌ FAIL: Missing required columns.")

    except Exception as e:
        print(f"❌ TEST ERROR: {str(e)}")

if __name__ == "__main__":
    test_collaborator_sorting()