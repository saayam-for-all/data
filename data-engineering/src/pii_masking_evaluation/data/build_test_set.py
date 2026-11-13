"""Builds test_set.jsonl, the labelled test set for issue #585.

Every text is made up. Phone numbers use 555-01xx style or other fictional
ranges, emails use example domains or made-up mailboxes, and every person is
fictional. Nothing here comes from the real requests table.

Each item is one request (req_subj + req_desc) with every personal detail it
contains listed in `pii`. Each text is listed once; every whole-word occurrence
of it in the subject or description counts (see evaluate.py). An entity is
labelled with:
  type        NAME, PHONE, EMAIL, ADDRESS, ID, CARD, URL
  text        the exact text that must disappear
  registered  NAME only: True if this person is in data/mock_users.csv, i.e.
              a Saayam user that a users-table lookup could know about

Run:  python build_test_set.py   (rewrites test_set.jsonl and checks it)
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def n(text, registered):
    return {"type": "NAME", "text": text, "registered": registered}


def p(type_, text):
    return {"type": type_, "text": text}


# (id, subject, description, [entities], tags)
ITEMS = [
    # ------------------------------------------------ phones, many formats
    ("T01", "Need groceries this week",
     "We ran out of food. Please call me at (408) 555-0134 any time after 5pm.",
     [p("PHONE", "(408) 555-0134")], ["phone"]),
    ("T02", "Ride to clinic",
     "I need a ride to my appointment on Friday. My cell is 408.555.0177.",
     [p("PHONE", "408.555.0177")], ["phone"]),
    ("T03", "Help moving furniture",
     "Moving out on Saturday, need two people to help lift a couch. Text 4085550123.",
     [p("PHONE", "4085550123")], ["phone"]),
    ("T04", "Tutoring for my son",
     "Looking for a math tutor for 8th grade. Reach me on +1 408 555 0145 or WhatsApp.",
     [p("PHONE", "+1 408 555 0145")], ["phone"]),
    ("T05", "Need help with rent",
     "Lost my job last month. My number in India is +91 98765 43210, I am visiting family.",
     [p("PHONE", "+91 98765 43210")], ["phone", "international"]),
    ("T06", "Medicine pickup",
     "Can someone pick up my prescription? Call my home line 555-0199.",
     [p("PHONE", "555-0199")], ["phone", "7-digit"]),
    ("T07", "Help with job application",
     "I need help filling online forms. My phone is four zero eight five five five zero one nine two.",
     [p("PHONE", "four zero eight five five five zero one nine two")], ["phone", "spelled-out"]),
    ("T08", "Food for family of five",
     "Please contact 408 five five five 0161 when food is ready, thank you.",
     [p("PHONE", "408 five five five 0161")], ["phone", "spelled-out"]),
    ("T09", "Translator needed",
     "Need a Spanish translator for a school meeting. UK number while abroad: +44 20 7946 0958.",
     [p("PHONE", "+44 20 7946 0958")], ["phone", "international"]),
    ("T10", "Wheelchair ramp",
     "Need a ramp built at the front door. Phone 408-555-0188 ext. 12.",
     [p("PHONE", "408-555-0188")], ["phone"]),

    # ------------------------------------------------ emails
    ("T11", "Laptop for school",
     "My daughter needs a laptop for online classes. Email me at maria.lopez@example.com.",
     [p("EMAIL", "maria.lopez@example.com")], ["email"]),
    ("T12", "Resume review",
     "Please send feedback to raghu dot priya at gmail dot com, I check it daily.",
     [p("EMAIL", "raghu dot priya at gmail dot com")], ["email", "obfuscated"]),
    ("T13", "Winter clothes",
     "Need jackets for two kids. You can write to kwame_m [at] example [dot] org.",
     [p("EMAIL", "kwame_m [at] example [dot] org")], ["email", "obfuscated"]),
    ("T14", "Contact me by email",
     "Email: chou.meiling+help@example.net",
     [p("EMAIL", "chou.meiling+help@example.net")], ["email"]),

    # ------------------------------------------------ names, registered users
    ("T15", "Groceries for Maria Lopez",
     "Maria Lopez is my neighbour and cannot walk to the store.",
     [n("Maria Lopez", True), n("Maria Lopez", True)], ["name", "subject"]),
    ("T16", "Help for elderly father",
     "My father José Hernández needs someone to check on him twice a week.",
     [n("José Hernández", True)], ["name", "non-english"]),
    ("T17", "Need a ride",
     "Hi, this is Oluwaseun Adeyemi. I need a ride to the DMV on Monday.",
     [n("Oluwaseun Adeyemi", True)], ["name", "non-english"]),
    ("T18", "Meal delivery",
     "Please deliver meals to Mohammed Al-Rashid, he just had surgery.",
     [n("Mohammed Al-Rashid", True)], ["name", "non-english"]),
    ("T19", "Help with English classes",
     "I am Nguyễn Thị Lan and I want to learn English to find work.",
     [n("Nguyễn Thị Lan", True)], ["name", "non-english"]),
    ("T20", "Babysitting",
     "Need babysitting on Tuesday evening. Ask for Fatima Zahra Benali at the front desk.",
     [n("Fatima Zahra Benali", True)], ["name", "non-english"]),
    ("T21", "Computer help",
     "My grandmother Aiko Tanaka needs help setting up video calls with family.",
     [n("Aiko Tanaka", True)], ["name", "non-english"]),
    ("T22", "Food assistance",
     "my name is guadalupe ramírez and we need food for this week",
     [n("guadalupe ramírez", True)], ["name", "lowercase", "non-english"]),
    ("T23", "Yard cleanup",
     "Chinedu Okafor here, need help clearing fallen branches after the storm.",
     [n("Chinedu Okafor", True)], ["name", "non-english"]),
    ("T24", "Hospital visit company",
     "Lakshmi Narayanan would like someone to sit with her during dialysis.",
     [n("Lakshmi Narayanan", True)], ["name", "non-english"]),
    ("T25", "Bike repair",
     "Need my bike fixed to get to work. Thanks, Björn Lindqvist",
     [n("Björn Lindqvist", True)], ["name", "non-english"]),
    ("T26", "School supplies",
     "Ms. Siddiqui, my son's teacher, said he needs a calculator. Please contact Ayesha Siddiqui (me).",
     [n("Siddiqui", True), n("Ayesha Siddiqui", True)], ["name", "non-english"]),
    ("T27", "Moving boxes",
     "Dmitri Volkov needs boxes and tape for a move next week.",
     [n("Dmitri Volkov", True)], ["name", "non-english"]),
    ("T28", "Help for Siobhán",
     "Siobhán Ní Bhriain broke her arm and needs help with shopping.",
     [n("Siobhán", True), n("Siobhán Ní Bhriain", True)], ["name", "non-english"]),
    ("T29", "Thai interpreter",
     "Need a Thai speaker to help Anan Srisuk talk to his landlord.",
     [n("Anan Srisuk", True)], ["name", "non-english"]),
    ("T30", "Grocery run",
     "Thandiwe Dlamini cannot drive this month, needs weekly groceries.",
     [n("Thandiwe Dlamini", True)], ["name", "non-english"]),

    # ------------------------------------------------ names, NOT users (third parties)
    ("T31", "Visit my mother",
     "My mother Rosa Delgado lives alone and needs someone to visit on weekends.",
     [n("Rosa Delgado", False)], ["name", "not-registered"]),
    ("T32", "Help my neighbor",
     "My neighbor Mr. Haruto Sato fell last week and needs help with groceries.",
     [n("Haruto Sato", False)], ["name", "not-registered", "non-english"]),
    ("T33", "Caseworker follow-up",
     "Our caseworker Emily Carter said to post here for diapers and formula.",
     [n("Emily Carter", False)], ["name", "not-registered"]),
    ("T34", "Landlord dispute",
     "Need advice. Landlord Viktor Petrenko wants to evict us without notice.",
     [n("Viktor Petrenko", False)], ["name", "not-registered", "non-english"]),
    ("T35", "Pet care",
     "Please walk our dog while my husband Ikenna is in hospital.",
     [n("Ikenna", False)], ["name", "not-registered", "non-english", "first-name-only"]),

    # ------------------------------------------------ addresses
    ("T36", "Food delivery needed",
     "Please drop off the food at 1234 Oak Street, Apt 4B. Ring the bell twice.",
     [p("ADDRESS", "1234 Oak Street, Apt 4B")], ["address"]),
    ("T37", "Snow shoveling",
     "Driveway at 77 Maple Ave needs shoveling before Monday morning.",
     [p("ADDRESS", "77 Maple Ave")], ["address"]),
    ("T38", "Mail pickup",
     "I am traveling, please collect mail from PO Box 2210 for me.",
     [p("ADDRESS", "PO Box 2210")], ["address"]),
    ("T39", "Ride to work",
     "Pick me up from 4521 Stevens Creek Blvd, San Jose at 7am.",
     [p("ADDRESS", "4521 Stevens Creek Blvd")], ["address"]),
    ("T40", "Fix leaking sink",
     "Our sink is leaking. We live at the blue house on twelve Elm Road.",
     [p("ADDRESS", "twelve Elm Road")], ["address", "spelled-out"]),

    # ------------------------------------------------ ID numbers, cards, personal links
    ("T41", "Help with benefits form",
     "The form asks for my SSN 123-45-6789, can someone help me fill it in?",
     [p("ID", "123-45-6789")], ["id"]),
    ("T42", "Pay electricity bill",
     "Can someone pay my bill? My card is 4111 1111 1111 1111.",
     [p("CARD", "4111 1111 1111 1111")], ["card"]),
    ("T43", "Find me online",
     "You can message me on https://www.facebook.com/priya.r.example for details.",
     [p("URL", "https://www.facebook.com/priya.r.example")], ["url"]),

    # ------------------------------------------------ several details together
    ("T44", "Urgent: food and diapers",
     "This is Carmen Ruiz, call 650-555-0112 or email carmen.r@example.org. "
     "Address is 89 Pine Lane.",
     [n("Carmen Ruiz", True), p("PHONE", "650-555-0112"),
      p("EMAIL", "carmen.r@example.org"), p("ADDRESS", "89 Pine Lane")], ["mixed"]),
    ("T45", "Help for Wei Zhang",
     "Wei Zhang needs a ride to the airport. His number is (669) 555-0170.",
     [n("Wei Zhang", True), n("Wei Zhang", True), p("PHONE", "(669) 555-0170")],
     ["mixed", "non-english"]),
    ("T46", "Need help with taxes",
     "Rahul Verma, rahulv@example.com, 510 555 0193. Need help with tax filing.",
     [n("Rahul Verma", True), p("EMAIL", "rahulv@example.com"), p("PHONE", "510 555 0193")],
     ["mixed"]),
    ("T47", "Donation pickup",
     "Yusuf Demir has a sofa to donate, pick up at 300 Bay Road. Call five one zero, "
     "five five five, zero one four four.",
     [n("Yusuf Demir", True), p("ADDRESS", "300 Bay Road"),
      p("PHONE", "five one zero, five five five, zero one four four")], ["mixed", "spelled-out"]),
    ("T48", "Need a ride for Grace",
     "Grace Thompson needs a ride to church on Sunday, call 408-555-0150.",
     [n("Grace", True), n("Grace Thompson", True), p("PHONE", "408-555-0150")],
     ["mixed", "name-is-a-word"]),
    ("T49", "Hope needs a coat",
     "Hope Williams needs a winter coat, size M.",
     [n("Hope", True), n("Hope Williams", True)], ["name", "name-is-a-word"]),
    ("T50", "Help Jordan move",
     "Jordan Brooks is moving to a new apartment and needs a truck.",
     [n("Jordan", True), n("Jordan Brooks", True)], ["name", "name-is-a-word"]),

    # ------------------------------------------------ NO personal details (false-positive checks)
    ("C01", "Groceries for a family of four",
     "We need rice, beans, milk and vegetables for this week.", [], ["clean"]),
    ("C02", "Rent help",
     "Rent of $1,250 is due on 11/15/2026 and I am short by $400.", [], ["clean", "numbers"]),
    ("C03", "Childcare",
     "I have 3 kids aged 4, 7 and 12 and need after-school care twice a week.",
     [], ["clean", "numbers"]),
    ("C04", "Emergency info",
     "If it is an emergency please call 911. Otherwise any time this week is fine.",
     [], ["clean", "numbers"]),
    ("C05", "Grace period ended",
     "The grace period on my rent ended and I need help paying it.",
     [], ["clean", "name-is-a-word"]),
    ("C06", "Hope to find work",
     "Hope someone can help me write a cover letter. Will pay it forward.",
     [], ["clean", "name-is-a-word"]),
    ("C07", "Clinic on Mission Blvd",
     "Need a ride to the free clinic on Mission Blvd in Fremont.",
     [], ["clean", "place"]),
    ("C08", "Help after flood",
     "Our basement flooded during the storm. Need help moving things upstairs.",
     [], ["clean"]),
    ("C09", "Food bank information",
     "Where is the nearest food bank? I saw https://www.211.org but could not find one.",
     [], ["clean", "public-url"]),
    ("C10", "Refugee family from Jordan",
     "A family that just arrived from Jordan needs furniture and kitchen items.",
     [], ["clean", "name-is-a-word", "place"]),
    ("C11", "Laptop repair",
     "My laptop model 15-ay041wm will not turn on. Need someone who knows computers.",
     [], ["clean", "numbers"]),
    ("C12", "Bus pass",
     "Need a monthly bus pass for route 22 to get to my new job.", [], ["clean", "numbers"]),
    ("C13", "Medicine",
     "I take 2 pills a day and the pharmacy is closed on Sunday.", [], ["clean", "numbers"]),
    ("C14", "Tutoring",
     "Looking for a chemistry tutor, high school level, 2 hours per week.", [], ["clean"]),
    ("C15", "Wheelchair",
     "Need a used wheelchair, budget under 150 dollars.", [], ["clean", "numbers"]),
    ("C16", "Tax help",
     "I need help with my 2025 tax return and form 1040.", [], ["clean", "numbers"]),
    ("C17", "Phone plan",
     "My phone was cut off. Need help finding a cheap phone plan.", [], ["clean"]),
    ("C18", "Help at Lincoln Elementary",
     "Volunteers needed to paint the fence at Lincoln Elementary on Saturday.",
     [], ["clean", "place"]),
    ("C19", "May food drive",
     "May I get a box from the food drive? We are a family of 6.", [], ["clean", "name-is-a-word"]),
    ("C20", "Order tracking",
     "Donated items were shipped, tracking number 1Z999AA10123456784.", [], ["clean", "numbers"]),
]


# Written AFTER approach 4 was finished and never used to tune any approach.
# Scores on this set show how much approach 4 was fitted to ITEMS above.
HOLDOUT = [
    ("H01", "Need diapers",
     "Spoke with Aleksandra Nowak at the shelter, she said to ask here. Size 4 diapers please.",
     [n("Aleksandra Nowak", False)], ["name", "not-registered", "non-english"]),
    ("H02", "Signed up for meals",
     "We need meals for two weeks after the baby arrives. Signed: Tomás Ortega",
     [n("Tomás Ortega", False)], ["name", "not-registered", "non-english"]),
    ("H03", "Contact person",
     "Contact person - Nadia Haddad, best reached in the evening.",
     [n("Nadia Haddad", False)], ["name", "not-registered", "non-english"]),
    ("H04", "PLEASE HELP",
     "PLEASE CALL SUNIL AT 408 555 0102 (CELL). NEED FOOD URGENTLY.",
     [n("SUNIL", False), p("PHONE", "408 555 0102")], ["name", "phone", "all-caps"]),
    ("H05", "Help for my uncle",
     "My uncle Bao is 80 and needs someone to help him with his medicines.",
     [n("Bao", False)], ["name", "not-registered", "first-name-only"]),
    ("H06", "Ride needed",
     "Ride needed from Lakshmi's house to the temple on Sunday morning.",
     [n("Lakshmi", True)], ["name", "possessive"]),
    ("H07", "Phone number",
     "phone: 408\u2011555\u20110133 (please leave a voicemail)",
     [p("PHONE", "408\u2011555\u20110133")], ["phone", "unicode-hyphen"]),
    ("H08", "Moving help",
     "Moving out of my place on the weekend, my cell is (510)5550187.",
     [p("PHONE", "(510)5550187")], ["phone"]),
    ("H09", "Family in Mexico",
     "My sister in Mexico City needs medicine sent. Her WhatsApp is +52 55 1234 5678.",
     [p("PHONE", "+52 55 1234 5678")], ["phone", "international"]),
    ("H10", "Email",
     "Questions? Write to OLU.ADEYEMI@EXAMPLE.ORG.",
     [p("EMAIL", "OLU.ADEYEMI@EXAMPLE.ORG")], ["email", "all-caps"]),
    ("H11", "Groceries",
     "Deliver to Unit 5, 210 W Santa Clara St please.",
     [p("ADDRESS", "Unit 5, 210 W Santa Clara St")], ["address"]),
    ("H12", "Fix fence",
     "Fence broke at apt 3, 45 river rd. Need a handyman.",
     [p("ADDRESS", "apt 3, 45 river rd")], ["address", "lowercase"]),
    ("H13", "Dog walking",
     "Dog walker needed for Mrs. Kowalczyk while she recovers from surgery.",
     [n("Kowalczyk", False)], ["name", "not-registered", "non-english"]),
    ("H14", "Lunch for seniors",
     "Volunteer coordinator is Wei, number 669 555 0119, she will share the list.",
     [n("Wei", True), p("PHONE", "669 555 0119")], ["mixed"]),
    ("H15", "School form",
     "Need help with a school form for my kid, my email is lan.nguyen.92 at yahoo dot com",
     [p("EMAIL", "lan.nguyen.92 at yahoo dot com")], ["email", "obfuscated"]),
    ("H16", "Car seat",
     "Need a car seat. I'm Precious Moyo, you can reach me on 408-555-0128.",
     [n("Precious Moyo", False), p("PHONE", "408-555-0128")], ["mixed", "name-is-a-word"]),
    ("HC1", "Park cleanup", "Volunteers needed for the Will Rogers Park cleanup on Saturday.",
     [], ["clean", "name-is-a-word", "place"]),
    ("HC2", "Rent went up", "Rent increased from 1800 to 2100 and I cannot cover the gap.",
     [], ["clean", "numbers"]),
    ("HC3", "Info line", "I called 211 but they told me to post here.", [], ["clean", "numbers"]),
    ("HC4", "Coat drive", "Is the Salvation Army coat drive still open this week?",
     [], ["clean", "place"]),
    ("HC5", "Kids shoes", "Need shoes for my two kids, sizes 13 and 2.", [], ["clean", "numbers"]),
    ("HC6", "Interview clothes", "I have a job interview at Target on Monday and need a shirt.",
     [], ["clean", "place"]),
    ("HC7", "Faith based help", "Looking for a church or mosque food pantry near Santa Clara.",
     [], ["clean", "place"]),
    ("HC8", "Bills", "My PG&E bill of $310 is overdue, account is in my name.",
     [], ["clean", "numbers"]),
]


def build(items=ITEMS):
    out, ids = [], set()
    for item_id, subj, desc, ents, tags in items:
        assert item_id not in ids, item_id
        ids.add(item_id)
        joined = subj + "\n" + desc
        unique = []
        for e in ents:
            assert e["text"] in joined, f"{item_id}: {e['text']!r} not in text"
            if e not in unique:
                unique.append(e)
        ents = unique
        out.append({"id": item_id, "subject": subj, "description": desc,
                    "has_pii": bool(ents), "pii": ents, "tags": tags})
    return out


def main():
    for name, source in (("test_set.jsonl", ITEMS), ("holdout_set.jsonl", HOLDOUT)):
        items = build(source)
        path = os.path.join(HERE, name)
        with open(path, "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        pii = sum(it["has_pii"] for it in items)
        print(f"{name}: {len(items)} items, {pii} with personal details, {len(items) - pii} without")


if __name__ == "__main__":
    main()
