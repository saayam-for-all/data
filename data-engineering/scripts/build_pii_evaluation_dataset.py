"""Build the synthetic labelled dataset and users fixture for Issue #585.

Every name, phone number, email, address and identifier below is invented.
Phone numbers use reserved fictional ranges where they exist (US 555-01xx,
UK Ofcom drama ranges), emails use example domains, and card numbers are
public test numbers.

Entity spans are computed here, so the JSONL never needs hand-written offsets.
Run from ``data-engineering/``::

    python -m scripts.build_pii_evaluation_dataset
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "pii_evaluation"
DATASET_PATH = FIXTURE_DIR / "request_texts.jsonl"
USERS_PATH = FIXTURE_DIR / "synthetic_users.csv"

# (id, language, tags, text, [(entity type, exact text, in users table or None)])
RECORDS = [
    ("C01", "en", [], "Our family lost everything in the flood and we need drinking water and blankets for three children.", []),
    ("C02", "en", [], "I need help applying for food assistance; the form asks for documents I do not understand.", []),
    ("C03", "en", [], "The shelter on the north side closes at 9 pm. Is there another place open overnight?", []),
    ("C04", "en", [], "Looking for a volunteer who can translate a hospital discharge letter from Arabic to English.", []),
    ("C05", "en", ["fp_trap_number"], "My rent went up by $350 this month and I cannot pay it. Are there emergency rent programs?", []),
    ("C06", "en", ["fp_trap_date"], "The clinic appointment is on 2026-03-14 at 10:30. I need a ride there and back.", []),
    ("C07", "en", ["fp_trap_date"], "We need 25 food kits and 40 hygiene kits for the camp before 15/03/2026.", []),
    ("C08", "en", ["fp_trap_number"], "Order number 4521-7789-3310 for the wheelchair still has not arrived.", []),
    ("C09", "en", ["fp_trap_number"], "I am 72 years old and need help carrying groceries up to the 4th floor.", []),
    ("C10", "en", [], "Please share the hotline number for the local food bank.", []),
    ("C11", "en", ["fp_trap_name_word"], "I hope May brings better weather; right now we need a space heater.", []),
    ("C12", "en", ["fp_trap_name_word"], "Grace period for the electricity bill ends Friday. Can someone help us pay the bill?", []),
    ("C13", "en", ["fp_trap_name_word"], "Victoria Park community kitchen serves lunch on weekdays. Is it open during the holidays?", []),
    ("C14", "en", ["fp_trap_name_word"], "We moved from Jordan last year and need help enrolling the kids in school.", []),
    ("C15", "en", [], "Need diapers in size 4 and baby formula, around 3 cans, for a 9 month old.", []),
    ("C16", "en", ["fp_trap_number"], "The bus route 1205 stopped running and I can no longer reach the pharmacy.", []),
    ("C17", "es", ["non_english"], "Necesito ayuda con comida y medicinas para mi madre, que está enferma.", []),
    ("C18", "hi", ["non_english"], "मुझे बच्चों के लिए गर्म कपड़े चाहिए, सर्दी बहुत ज़्यादा है।", []),
    ("C19", "en", ["fp_trap_number"], "The donation receipt total was 1,250,000 rupees for the whole village water project.", []),
    ("C20", "en", ["fp_trap_url"], "Information is available at https://www.example.org/relief but the page will not load on my phone.", []),
    ("C21", "en", ["fp_trap_pii_words"], "Can someone explain how to fill in the ZIP code and state fields on the benefits website?", []),
    ("C22", "en", [], "We need help repairing the roof at the community center after the storm.", []),
    ("C23", "en", ["fp_trap_number"], "Our group of 12 volunteers can deliver meals between 18:00 and 20:00 on Saturdays.", []),
    ("C24", "en", ["fp_trap_name_word"], "Mark the boxes as fragile because they contain glass jars of baby food.", []),
    ("C25", "en", ["fp_trap_address"], "The temperature dropped to -15 and the heating in Building 7 is broken.", []),
    ("C26", "fr", ["non_english"], "Bonjour, nous avons besoin de couvertures et de nourriture pour deux familles.", []),
    ("C27", "mixed", ["mixed_language"], "Necesito ayuda with my English homework, por favor.", []),

    ("P01", "en", [], "Please call me at 202-555-0147 about the food delivery.", [("PHONE", "202-555-0147", None)]),
    ("P02", "en", [], "You can reach me at (415) 555-0199 after 6 pm.", [("PHONE", "(415) 555-0199", None)]),
    ("P03", "en", [], "My number is 202.555.0182 and I need a ride to dialysis on Tuesday.", [("PHONE", "202.555.0182", None)]),
    ("P04", "en", [], "Text 6175550123 when the volunteer is outside.", [("PHONE", "6175550123", None)]),
    ("P05", "en", ["country_code"], "Call +1 312 555 0110 for the pickup, it is a wheelchair.", [("PHONE", "+1 312 555 0110", None)]),
    ("P06", "en", ["international_phone"], "Contact me on +44 20 7946 0958 about the winter coats.", [("PHONE", "+44 20 7946 0958", None)]),
    ("P07", "en", ["international_phone"], "My WhatsApp is +91 98765 43210 because my English is not good.", [("PHONE", "+91 98765 43210", None)]),
    ("P08", "es", ["international_phone", "non_english"], "Llámame al +52 55 1234 5678, necesito ayuda con la renta.", [("PHONE", "+52 55 1234 5678", None)]),
    ("P09", "en", ["international_phone"], "Call 020 7946 0321 between 9 and 5 on weekdays.", [("PHONE", "020 7946 0321", None)]),
    ("P10", "en", ["spelled_out"], "My phone is five five five, two one four, eight eight nine zero.", [("PHONE", "five five five, two one four, eight eight nine zero", None)]),
    ("P11", "en", ["spelled_out"], "The number is nine one seven five five five zero one nine eight, please call after lunch.", [("PHONE", "nine one seven five five five zero one nine eight", None)]),
    ("P12", "en", [], "Email me at amira.haddad@example.com with the shelter details.", [("EMAIL", "amira.haddad@example.com", None)]),
    ("P13", "en", [], "My email is j.okafor+help@example.org and I check it daily.", [("EMAIL", "j.okafor+help@example.org", None)]),
    ("P14", "en", ["spelled_out"], "Send the form to rosa dot delgado at example dot com please.", [("EMAIL", "rosa dot delgado at example dot com", None)]),
    ("P15", "en", [], "My name is Priya Raghunathan and I need help moving a bed.", [("PERSON", "Priya Raghunathan", True)]),
    ("P16", "en", [], "Wei Zhang needs a ride to the pharmacy on Friday.", [("PERSON", "Wei Zhang", True)]),
    ("P17", "en", [], "Please ask Nguyen Thi Lan which groceries are suitable for her diet.", [("PERSON", "Nguyen Thi Lan", True)]),
    ("P18", "en", ["third_party_name"], "My grandmother, Esperanza Morales, needs someone to check on her daily.", [("PERSON", "Esperanza Morales", False)]),
    ("P19", "en", [], "Oluwaseun Adeyemi is requesting school supplies for two children.", [("PERSON", "Oluwaseun Adeyemi", True)]),
    ("P20", "en", [], "I am Fatima Al-Sayed and my children need winter clothes.", [("PERSON", "Fatima Al-Sayed", True)]),
    ("P21", "en", ["third_party_name"], "Contact my neighbor Dmitri Volkov because he has the spare key.", [("PERSON", "Dmitri Volkov", False)]),
    ("P22", "en", ["accented_name"], "Chloé Lefèvre needs help getting to the community center.", [("PERSON", "Chloé Lefèvre", True)]),
    ("P23", "hi", ["non_english", "non_latin_script"], "मेरा नाम अनीता शर्मा है और मुझे राशन चाहिए।", [("PERSON", "अनीता शर्मा", True)]),
    ("P24", "zh", ["non_english", "non_latin_script"], "我叫王伟，需要帮助搬家。", [("PERSON", "王伟", True)]),
    ("P25", "es", ["non_english"], "Hola, soy Javier Ortega y necesito ayuda con medicinas para mi hijo.", [("PERSON", "Javier Ortega", True)]),
    ("P26", "en", ["third_party_name"], "Kwame Mensah said I should post here because we need food for the weekend.", [("PERSON", "Kwame Mensah", False)]),
    ("P27", "en", [], "Ask for Hiroshi Tanaka at the front desk when you arrive.", [("PERSON", "Hiroshi Tanaka", True)]),
    ("P28", "en", [], "My address is 18 Maple Street, Springfield, for the furniture drop.", [("ADDRESS", "18 Maple Street, Springfield", None)]),
    ("P29", "en", [], "Please deliver the food box to 42 Cedar Ave, Apt 5B.", [("ADDRESS", "42 Cedar Ave, Apt 5B", None)]),
    ("P30", "en", ["non_english_address"], "I live at 7 Rue des Fleurs, Lyon, and need winter clothes.", [("ADDRESS", "7 Rue des Fleurs, Lyon", None)]),
    ("P31", "es", ["non_english"], "Vivo en Calle Mayor 23, 2º izquierda, Madrid; necesito una estufa.", [("ADDRESS", "Calle Mayor 23, 2º izquierda, Madrid", None)]),
    ("P32", "en", [], "We are at 1200 Pine Boulevard, Building C, unit 14, please bring blankets.", [("ADDRESS", "1200 Pine Boulevard, Building C, unit 14", None)]),
    ("P33", "en", ["non_english_address"], "House 14, Lane 3, Sector 9, Dwarka, New Delhi 110075 needs medicines urgently.", [("ADDRESS", "House 14, Lane 3, Sector 9, Dwarka, New Delhi 110075", None)]),
    ("P34", "en", [], "My SSN is 123-45-6789 and the form says it is required.", [("NATIONAL_ID", "123-45-6789", None)]),
    ("P35", "en", [], "Aadhaar number 2345 6789 0123 is on the ration card application.", [("NATIONAL_ID", "2345 6789 0123", None)]),
    ("P36", "en", [], "The card for reimbursement is 4111 1111 1111 1111.", [("CARD", "4111 1111 1111 1111", None)]),
    ("P37", "en", [], "Charge the delivery fee to 5555-5555-5555-4444 please.", [("CARD", "5555-5555-5555-4444", None)]),
    ("P38", "en", [], "My passport number is X1234567 and I need help with the visa form.", [("NATIONAL_ID", "X1234567", None)]),
    ("P39", "en", ["multi_entity"], "I'm Leila Nouri, call me at 617-555-0134 or email leila.nouri@example.net, address 55 Elm Road, Apt 3.",
     [("PERSON", "Leila Nouri", True), ("PHONE", "617-555-0134", None), ("EMAIL", "leila.nouri@example.net", None), ("ADDRESS", "55 Elm Road, Apt 3", None)]),
    ("P40", "es", ["multi_entity", "international_phone", "non_english", "third_party_name"], "Para mi abuela Carmen Ruiz: Avenida Central 45, San José. Tel. 8888-1234.",
     [("PERSON", "Carmen Ruiz", False), ("ADDRESS", "Avenida Central 45, San José", None), ("PHONE", "8888-1234", None)]),
    ("P41", "en", ["multi_entity", "international_phone", "third_party_name"], "Contact Ahmed Khan (+92 300 1234567) or his wife Sana Khan at sana.khan@example.com.",
     [("PERSON", "Ahmed Khan", True), ("PHONE", "+92 300 1234567", None), ("PERSON", "Sana Khan", False), ("EMAIL", "sana.khan@example.com", None)]),
    ("P42", "mixed", ["multi_entity", "mixed_language"], "Mi nombre es Lucía Fernández, my number is 305-555-0177, necesito comida.",
     [("PERSON", "Lucía Fernández", True), ("PHONE", "305-555-0177", None)]),
    ("P43", "en", ["multi_entity", "third_party_name"], "Please help my friend Tomás, his number is 312 555 0145.",
     [("PERSON", "Tomás", False), ("PHONE", "312 555 0145", None)]),
    ("P44", "en", [], "Visit my profile https://facebook.com/maria.santos.1987 to see photos of the damage.",
     [("URL", "https://facebook.com/maria.santos.1987", None)]),
    ("P45", "en", ["multi_entity", "third_party_name"], "I am staying with Grace Okonkwo at 9 Hope Street.",
     [("PERSON", "Grace Okonkwo", False), ("ADDRESS", "9 Hope Street", None)]),
    ("P46", "mixed", ["multi_entity", "mixed_language", "third_party_name"], "Hi, necesito ayuda, my son Mateo Herrera is sick, llámame al 787-555-0142.",
     [("PERSON", "Mateo Herrera", False), ("PHONE", "787-555-0142", None)]),
    ("P47", "mixed", ["multi_entity", "mixed_language", "international_phone", "third_party_name"], "Mera naam Ravi Verma hai, please call 98100 12345 for ration delivery.",
     [("PERSON", "Ravi Verma", False), ("PHONE", "98100 12345", None)]),
]

# Synthetic stand-in for the ``users`` name columns. Some names appear in the
# request texts (requesters), some are common English words (false-positive
# risk for single-token lookup), and the rest are unrelated users.
USERS = [
    ("Priya", "", "Raghunathan", "Priya Raghunathan"),
    ("Wei", "", "Zhang", "Wei Zhang"),
    ("Lan", "Thi", "Nguyen", "Nguyen Thi Lan"),
    ("Oluwaseun", "", "Adeyemi", "Oluwaseun Adeyemi"),
    ("Fatima", "", "Al-Sayed", "Fatima Al-Sayed"),
    ("Chloe", "", "Lefevre", "Chloe Lefevre"),
    ("अनीता", "", "शर्मा", "अनीता शर्मा"),
    ("伟", "", "王", "王伟"),
    ("Javier", "", "Ortega", "Javier Ortega"),
    ("Hiroshi", "", "Tanaka", "Hiroshi Tanaka"),
    ("Leila", "", "Nouri", "Leila Nouri"),
    ("Ahmed", "", "Khan", "Ahmed Khan"),
    ("Lucía", "", "Fernández", "Lucía Fernández"),
    ("Hope", "", "Williams", "Hope Williams"),
    ("May", "", "Lin", "May Lin"),
    ("Bill", "", "Turner", "Bill Turner"),
    ("Mark", "", "Johnson", "Mark Johnson"),
    ("Victoria", "", "Adams", "Victoria Adams"),
    ("Jordan", "", "Lee", "Jordan Lee"),
    ("Grace", "", "Liu", "Grace Liu"),
    ("Will", "", "Carter", "Will Carter"),
    ("Faith", "", "Mwangi", "Faith Mwangi"),
    ("Sophie", "", "Müller", "Sophie Müller"),
    ("Arjun", "", "Mehta", "Arjun Mehta"),
    ("Olga", "", "Ivanova", "Olga Ivanova"),
    ("Mohammed", "", "Rahman", "Mohammed Rahman"),
    ("Ana", "", "Silva", "Ana Silva"),
    ("Kenji", "", "Watanabe", "Kenji Watanabe"),
    ("Aisha", "", "Bello", "Aisha Bello"),
    ("Daniel", "", "Cohen", "Daniel Cohen"),
    ("Yusuf", "", "Demir", "Yusuf Demir"),
    ("Mei", "", "Chen", "Mei Chen"),
    ("Carlos", "", "Mendoza", "Carlos Mendoza"),
    ("Ingrid", "", "Larsen", "Ingrid Larsen"),
    ("Samuel", "", "Osei", "Samuel Osei"),
]


def build_records() -> list[dict]:
    """Return the dataset records with computed entity spans."""
    records = []
    for record_id, language, tags, text, entities in RECORDS:
        cursor = 0
        built = []
        for entity_type, value, in_users in entities:
            start = text.find(value, cursor)
            if start < 0:
                raise ValueError(f"{record_id}: {value!r} not found after offset {cursor}")
            entity = {"type": entity_type, "start": start, "end": start + len(value), "text": value}
            if entity_type == "PERSON":
                entity["in_users_table"] = in_users
            built.append(entity)
            cursor = start + len(value)
        records.append({
            "id": record_id,
            "text": text,
            "contains_pii": bool(built),
            "language": language,
            "entity_types": sorted({entity["type"] for entity in built}),
            "entities": built,
            "tags": tags,
        })
    return records


def render_dataset() -> str:
    """Return the JSONL text of the dataset."""
    return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in build_records())


def render_users() -> str:
    """Return the CSV text of the synthetic users fixture."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["user_id", "first_name", "middle_name", "last_name", "full_name"])
    for number, (first, middle, last, full) in enumerate(USERS, start=1):
        writer.writerow([f"SYN-{number:04d}", first, middle, last, full])
    return buffer.getvalue()


def main() -> None:
    """Write both fixtures."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    DATASET_PATH.write_text(render_dataset(), encoding="utf-8")
    USERS_PATH.write_text(render_users(), encoding="utf-8")
    print(f"Wrote {len(RECORDS)} records to {DATASET_PATH.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {len(USERS)} users to {USERS_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
