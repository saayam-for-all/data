"""Labelled test set for issue #585 (masking personal details in request text).

Every request below is made up. No text or name comes from the real
``requests`` or ``users`` tables. People marked as registered users are listed
in ``mock_users.csv``; everyone else in the texts is a non-user, so the
users-table lookup cannot know them.

Each record has:
  id      main set: P01-P50 contain personal details, C01-C22 contain none
          holdout set: H01-H20 contain personal details, HC01-HC10 contain none
  subj    req_subj
  desc    req_desc
  pii     list of {"field", "text", "type"}: the exact substring that must be
          removed and its category (NAME, PHONE, EMAIL, ADDRESS, ID, CARD,
          URL, DOB)

Run ``python build_test_set.py`` to validate every label and rewrite
``test_set.jsonl`` and ``holdout_set.jsonl``.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (id, req_subj, req_desc, [(text, type), ...]). The field of each label is
# found automatically (subject first, then description).
RECORDS = [
    ("P01", "Need groceries this week",
     "We ran out of food. Please call me at 571-555-0142 after 5pm.",
     [("571-555-0142", "PHONE")]),
    ("P02", "Ride to clinic",
     "My appointment is Friday morning. Text me on (703) 555 0198 if you can drive.",
     [("(703) 555 0198", "PHONE")]),
    ("P03", "Help moving furniture",
     "Contact me at maria.gonzalez84@example.com, I'm free on weekends.",
     [("maria.gonzalez84@example.com", "EMAIL")]),
    ("P04", "Food for my family",
     "Hi, my name is Priya Venkataraman and we need rice and lentils for 4 people.",
     [("Priya Venkataraman", "NAME")]),
    ("P05", "Wheelchair ramp",
     "I live at 1428 Elm Street, Apt 3B, Reston VA 20190 and need a small ramp built.",
     [("1428 Elm Street, Apt 3B", "ADDRESS")]),
    ("P06", "Tutoring for my son",
     "My son Mateo needs help with algebra. You can reach my husband Wei Zhang at +1 202 555 0175.",
     [("Mateo", "NAME"), ("Wei Zhang", "NAME"), ("+1 202 555 0175", "PHONE")]),
    ("P07", "Medicine pickup",
     "Please pick up my prescription. My phone number is five seven one, five five five, zero one nine three.",
     [("five seven one, five five five, zero one nine three", "PHONE")]),
    ("P08", "Rent help",
     "I am Oluwaseun Adeyemi, a single mother of two, and I am short on rent this month.",
     [("Oluwaseun Adeyemi", "NAME")]),
    ("P09", "Phone call needed",
     "Call 9876543210 (India) and ask for Lakshmi.",
     [("9876543210", "PHONE"), ("Lakshmi", "NAME")]),
    ("P10", "Help with groceries",
     "Email: fatima dot alsayed at gmail dot com",
     [("fatima dot alsayed at gmail dot com", "EMAIL")]),
    ("P11", "Winter clothes",
     "Drop off at 77 Maple Ave, Herndon. Ring the bell twice.",
     [("77 Maple Ave", "ADDRESS")]),
    ("P12", "Translation help",
     "Necesito ayuda con documentos. Me llamo José Hernández, mi teléfono es 555-201-7788.",
     [("José Hernández", "NAME"), ("555-201-7788", "PHONE")]),
    ("P13", "Job application help",
     "Please review my resume. My SSN is 123-45-6789 if the form needs it.",
     [("123-45-6789", "ID")]),
    ("P14", "Paying a bill",
     "Can someone pay my electricity bill? Card 4111 1111 1111 1111 exp 09/27.",
     [("4111 1111 1111 1111", "CARD")]),
    ("P15", "Elderly neighbor check-in",
     "My neighbour Dmitri Volkov is 82 and lives alone; his number is 703.555.0123.",
     [("Dmitri Volkov", "NAME"), ("703.555.0123", "PHONE")]),
    ("P16", "Groceries",
     "aiko.tanaka@example.org - please deliver Tuesday",
     [("aiko.tanaka@example.org", "EMAIL")]),
    ("P17", "Need a ride",
     "Pickup from 3300 Fairfax Drive, Arlington around 9. Ask for Mr. Mehta.",
     [("3300 Fairfax Drive", "ADDRESS"), ("Mehta", "NAME")]),
    ("P18", "Help for my mom",
     "My mother Siobhan O'Connor needs someone to help her with shopping.",
     [("Siobhan O'Connor", "NAME")]),
    ("P19", "Car seat",
     "WhatsApp +91 98450 12345 anytime.",
     [("+91 98450 12345", "PHONE")]),
    ("P20", "Cooking help",
     "Contact Lan Nguyen on 0412 345 678 (Australia).",
     [("Lan Nguyen", "NAME"), ("0412 345 678", "PHONE")]),
    ("P21", "Laptop for school",
     "My daughter Zainab Okafor needs a laptop for online classes.",
     [("Zainab Okafor", "NAME")]),
    ("P22", "Tax forms",
     "Hello, this is Tomasz Kowalski. I need help filing taxes. Email tkowalski@example.net.",
     [("Tomasz Kowalski", "NAME"), ("tkowalski@example.net", "EMAIL")]),
    ("P23", "Food bank directions",
     "I'm at 15 Rue de la Paix, call me 0612345678.",
     [("15 Rue de la Paix", "ADDRESS"), ("0612345678", "PHONE")]),
    ("P24", "Help with forms",
     "My name is grace kim and I need help with a housing application.",
     [("grace kim", "NAME")]),
    ("P25", "Dog walking",
     "Hope Williams here, recovering from surgery, need someone to walk my dog.",
     [("Hope Williams", "NAME")]),
    ("P26", "Diapers",
     "Please call May Lin at 571 555 0110.",
     [("May Lin", "NAME"), ("571 555 0110", "PHONE")]),
    ("P27", "Ride to court",
     "You can find me on facebook https://facebook.com/rahul.mehta.77",
     [("https://facebook.com/rahul.mehta.77", "URL")]),
    ("P28", "Emergency food",
     "Text 2025550147. Thanks, Maria",
     [("2025550147", "PHONE"), ("Maria", "NAME")]),
    ("P29", "Furniture",
     "Address: 9 Birch Ct, Leesburg VA 20175",
     [("9 Birch Ct", "ADDRESS")]),
    ("P30", "Medical transport",
     "Patient: Ahmed Hassan, DOB 03/14/1958, needs transport to dialysis.",
     [("Ahmed Hassan", "NAME"), ("03/14/1958", "DOB")]),
    ("P31", "Phone number",
     "my number is 7 0 3 5 5 5 0 1 6 6",
     [("7 0 3 5 5 5 0 1 6 6", "PHONE")]),
    ("P32", "Help for Ravi",
     "Ravi Shankar needs grocery delivery, he is diabetic.",
     [("Ravi", "NAME"), ("Ravi Shankar", "NAME")]),
    ("P33", "Groceries",
     "Contact: chen.wei@example.com or 571-555-0199 ext 4",
     [("chen.wei@example.com", "EMAIL"), ("571-555-0199", "PHONE")]),
    ("P34", "Shelter",
     "I'm staying at my cousin's place, 210 Oak Lane Unit 5. Name is Kwame Mensah.",
     [("210 Oak Lane Unit 5", "ADDRESS"), ("Kwame Mensah", "NAME")]),
    ("P35", "School supplies",
     "Ask Ms. Iyer at the front desk, she knows my situation.",
     [("Iyer", "NAME")]),
    ("P36", "Help needed",
     "Please call nine eight seven six five four three two one zero.",
     [("nine eight seven six five four three two one zero", "PHONE")]),
    ("P37", "Passport renewal",
     "My passport number is K1234567, need help booking an appointment.",
     [("K1234567", "ID")]),
    ("P38", "Groceries for Mrs. Gonzalez",
     "She lives on the second floor and cannot carry bags.",
     [("Gonzalez", "NAME")]),
    ("P39", "Babysitter",
     "Reach me (Aisha) on +44 7700 900123.",
     [("Aisha", "NAME"), ("+44 7700 900123", "PHONE")]),
    ("P40", "Food",
     "मेरा नाम सुनीता शर्मा है, I need food for my kids.",
     [("सुनीता शर्मा", "NAME")]),
    ("P41", "Water bill",
     "Account holder: Juan Pablo Ortiz. Please help with $120.",
     [("Juan Pablo Ortiz", "NAME")]),
    ("P42", "Move help",
     "Moving from 500 King St to 12 Queen Street on Saturday.",
     [("500 King St", "ADDRESS"), ("12 Queen Street", "ADDRESS")]),
    ("P43", "Ride",
     "Pick me up near 8100 Lee Hwy, my name is Dmitri.",
     [("8100 Lee Hwy", "ADDRESS"), ("Dmitri", "NAME")]),
    ("P44", "Meals",
     "Contact my caseworker Ana Souza: ana.souza@example.org",
     [("Ana Souza", "NAME"), ("ana.souza@example.org", "EMAIL")]),
    ("P45", "Help please",
     "Call me at 1-800-555-0100 or my cell 571 5550123.",
     [("1-800-555-0100", "PHONE"), ("571 5550123", "PHONE")]),
    ("P46", "Tutor",
     "I'm Nguyen, student at the community college, need maths help.",
     [("Nguyen", "NAME")]),
    ("P47", "Hospital visit",
     "My wife Fatima is in the hospital, need someone to cook. My email is f_alsayed_99@example.com",
     [("Fatima", "NAME"), ("f_alsayed_99@example.com", "EMAIL")]),
    ("P48", "Phone repair",
     "My number: (571)555-0134. Name: O. Adeyemi",
     [("(571)555-0134", "PHONE"), ("O. Adeyemi", "NAME")]),
    ("P49", "Groceries",
     "Deliver to Flat 12, 4 Park Road, Mumbai 400050. Contact Rajesh Kumar.",
     [("Flat 12, 4 Park Road", "ADDRESS"), ("Rajesh Kumar", "NAME")]),
    ("P50", "Clothes donation pickup",
     "Please email me at wei.zhang [at] example [dot] com to arrange pickup.",
     [("wei.zhang [at] example [dot] com", "EMAIL")]),

    # ---- No personal details. Several contain traps: common words that are
    # also first names, long reference numbers, street names, public figures.
    ("C01", "Need groceries",
     "We need rice, beans and cooking oil for a family of five.", []),
    ("C02", "Ride to the food bank",
     "The Main Street food bank opens at 9am on Saturdays; I need a ride there.", []),
    ("C03", "Help with homework",
     "My kids need help with grade 7 math and reading, two evenings a week.", []),
    ("C04", "Grace period on rent",
     "I hope the landlord will give me a grace period. Can someone help me write a letter?", []),
    ("C05", "Winter coats",
     "Looking for 3 winter coats, sizes 8, 10 and 12.", []),
    ("C06", "Medicine",
     "I may need help picking up medicine from the CVS pharmacy every month.", []),
    ("C07", "Furniture",
     "We need a bed and 2 chairs after moving into a new apartment in May.", []),
    ("C08", "Transport",
     "Need transport to Inova Fairfax Hospital for a 10:30 appointment on 11/20.", []),
    ("C09", "Food",
     "Order #45821 from the pantry never arrived, please help.", []),
    ("C10", "Job search",
     "Looking for help writing a cover letter for a warehouse job paying $18.50/hour.", []),
    ("C11", "Tutoring",
     "Need an English tutor; I speak Spanish and Hindi at home.", []),
    ("C12", "Utilities",
     "Our electricity bill is 3 months overdue, around 450 dollars.", []),
    ("C13", "Help with taxes",
     "Need help with Form 1040 and the 2025 child tax credit.", []),
    ("C14", "Elder care",
     "My grandmother needs someone to check on her twice a week.", []),
    ("C15", "Donation",
     "Donate 25 cans of soup to the Red Cross shelter on Route 7.", []),
    ("C16", "Wheelchair",
     "Need a wheelchair for 6 to 8 weeks after knee surgery.", []),
    ("C17", "Prescription",
     "Insulin supply runs out on December 3rd; need help applying for assistance.", []),
    ("C18", "Car repair",
     "My 2012 Honda Civic needs new brakes, the quote was 300-400 dollars.", []),
    ("C19", "Counseling",
     "Looking for free counseling services near Washington DC.", []),
    ("C20", "Shelter",
     "Family of 4 needs emergency shelter for 2 nights, call the 211 hotline for details.", []),
    ("C21", "County paperwork",
     "Reference number 2026 1104 5567 89 from the county office, need help reading the letter.", []),
    ("C22", "Food drive",
     "Can volunteers help with the Martin Luther King Jr. Day food drive at the school?", []),
]


# Holdout set: written after approach 4's rules were frozen and never used to
# tune them. Its score is the honest estimate of how approach 4 generalises.
HOLDOUT_RECORDS = [
    ("H01", "Groceries", "pls call my mobile 240 555 0187 thx",
     [("240 555 0187", "PHONE")]),
    ("H02", "Help w/ kids", "I'm a single dad, Carlos Mendoza, two kids under 5.",
     [("Carlos Mendoza", "NAME")]),
    ("H03", "Ride to dialysis",
     "Mrs Okonkwo needs a ride Mon/Wed/Fri, she is at 4512 Willow Creek Rd.",
     [("Okonkwo", "NAME"), ("4512 Willow Creek Rd", "ADDRESS")]),
    ("H04", "Food", "you can email me anytime: sunita.sharma1975@yahoo.co.in",
     [("sunita.sharma1975@yahoo.co.in", "EMAIL")]),
    ("H05", "Phone", "My contact is +971 50 123 4567 (UAE).",
     [("+971 50 123 4567", "PHONE")]),
    ("H06", "Need help", "My daughter is Mei Ling and she needs school uniforms.",
     [("Mei Ling", "NAME")]),
    ("H07", "Moving", "New address is Apt 7, 22 Cedar Blvd, Ashburn VA.",
     [("Apt 7, 22 Cedar Blvd", "ADDRESS")]),
    ("H08", "Rent", "Landlord is Mr. Patel, his number is 571.555.0166.",
     [("Patel", "NAME"), ("571.555.0166", "PHONE")]),
    ("H09", "Medicine", "Ask for Hiroshi at the pharmacy counter.",
     [("Hiroshi", "NAME")]),
    ("H10", "Food", "Me llamo Ana María López y necesito comida para mis hijos.",
     [("Ana María López", "NAME")]),
    ("H11", "Ride", "call me on two zero two, five five five, zero one four four",
     [("two zero two, five five five, zero one four four", "PHONE")]),
    ("H12", "Tutoring", "Kindly contact Ms. Adaeze Nwosu, my sister, regarding tutoring.",
     [("Adaeze Nwosu", "NAME")]),
    ("H13", "Bills", "My driver license number is D123-4567-8901.",
     [("D123-4567-8901", "ID")]),
    ("H14", "Help", "This is Fatima again, the phone number changed to 703 555 0102.",
     [("Fatima", "NAME"), ("703 555 0102", "PHONE")]),
    ("H15", "Groceries", "Deliver to 1600 Pennsylvania Avenue NW please, ring twice. -Tom",
     [("1600 Pennsylvania Avenue", "ADDRESS"), ("Tom", "NAME")]),
    ("H16", "School form", "Child: Arjun Reddy, age 9. Parent: Kavya Reddy.",
     [("Arjun Reddy", "NAME"), ("Kavya Reddy", "NAME")]),
    ("H17", "Visit", "Please visit my grandpa Giuseppe Rossi, he lives alone.",
     [("Giuseppe Rossi", "NAME")]),
    ("H18", "Phone", "WhatsApp only: 0300-1234567",
     [("0300-1234567", "PHONE")]),
    ("H19", "Need diapers", "Diapers size 4 for baby Noah, contact noah.mom@example.com",
     [("Noah", "NAME"), ("noah.mom@example.com", "EMAIL")]),
    ("H20", "Shelter", "I'm Olga Petrova, I sleep in my car near the Walmart on Route 28.",
     [("Olga Petrova", "NAME")]),
    ("HC01", "Food", "Need baby formula and diapers for a 6 month old.", []),
    ("HC02", "Ride", "Need a ride to the Social Security office on Monday at 10am.", []),
    ("HC03", "Help", "Please call back when a volunteer is available.", []),
    ("HC04", "Rent", "Rent of $1,450 is due on the 1st; I can pay $700.", []),
    ("HC05", "Tutoring", "Need help preparing for the SAT in March.", []),
    ("HC06", "Clothes", "Looking for a size 10 dress for a job interview at Target.", []),
    ("HC07", "Utilities", "Account 00123 is overdue; can someone help negotiate a payment plan?", []),
    ("HC08", "Groceries", "Need halal groceries, we are a family of 6 new to Virginia.", []),
    ("HC09", "Transport", "Bus 5A stopped running near Lincoln Elementary, need rides to school.", []),
    ("HC10", "Help", "My phone is broken so please email through the app instead.", []),
]


def build(records=RECORDS, clean_prefixes=("C", "HC")):
    out = []
    for rid, subj, desc, labels in records:
        pii = []
        for text, kind in labels:
            if text in subj:
                field = "subj"
            elif text in desc:
                field = "desc"
            else:
                raise ValueError(f"{rid}: label {text!r} is not in the subject or description")
            pii.append({"field": field, "text": text, "type": kind})
        out.append({"id": rid, "subj": subj, "desc": desc, "pii": pii})

    ids = [r["id"] for r in out]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate ids in the test set")
    for r in out:
        clean = r["id"].startswith(clean_prefixes)
        if clean and r["pii"]:
            raise ValueError(f"{r['id']} is a clean record but has labels")
        if not clean and not r["pii"]:
            raise ValueError(f"{r['id']} has no labels")
    return out


def write(records, path):
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with_pii = sum(1 for r in records if r["pii"])
    print(f"Wrote {len(records)} requests to {path.name}: {with_pii} with personal details, "
          f"{len(records) - with_pii} without, {sum(len(r['pii']) for r in records)} labels.")


def main():
    write(build(RECORDS), HERE / "test_set.jsonl")
    write(build(HOLDOUT_RECORDS), HERE / "holdout_set.jsonl")


if __name__ == "__main__":
    main()
