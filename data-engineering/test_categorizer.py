import sys
sys.path.insert(0, '.')

from src.categorizer.handler import lambda_handler

tests = [
    ("Shelter", {"subject": "I need a place to stay tonight", "description": "I lost my apartment and have two kids with me."}),
    ("Food", {"subject": "Need food", "description": "My family hasn't eaten in two days, we need groceries."}),
    ("Empty", {"subject": "", "description": ""}),
    ("Healthcare", {"subject": "Mental health support", "description": "I have been feeling very anxious and depressed lately and need someone to talk to."}),
    ("Elderly", {"subject": "Help for my grandmother", "description": "My grandmother needs a ride to her doctor's appointment next week."}),
    ("Education", {"subject": "Need help with college application", "description": "I am applying to universities and need help reviewing my essay and SOP."}),
    ("Clothing", {"subject": "Need warm clothes", "description": "I don't have any winter clothes and it's getting very cold outside."}),
    ("Housing", {"subject": "Looking for a roommate", "description": "I need to find someone to share an apartment with to split the rent."}),
    ("Vague", {"subject": "Help", "description": "I just need some help please."}),
    ("Multilingual", {"subject": "Necesito comida", "description": "Mi familia no tiene que comer, necesitamos ayuda con alimentos."}),
]

for name, body in tests:
    result = lambda_handler({"body": body}, None)
    b = result["body"]
    print(f"Test [{name}]:")
    print(f"  Category   : {b['category']}")
    print(f"  Subcategory: {b['subcategory']}")
    print(f"  Confidence : {b['confidence']}")
    print(f"  Reasoning  : {b['reasoning']}")
    print()