"""Labelled test set for PII masking evaluation (issue #585).

Each item: (text, [(pii_substring, type), ...]).  Empty list => clean text.
All numbers/emails/addresses are fictional (555-01xx style numbers, invented people).
DEV is used while building detectors; HELDOUT was written before any detector
code and is only scored after the rules are frozen.
"""

DEV = [
    # ---- phone numbers in many formats ----
    ("Need a ride to dialysis on Friday. You can reach me at (480) 555-0142 after 5pm.", [("(480) 555-0142", "PHONE")]),
    ("Please call 480-555-0187, I can't always check email.", [("480-555-0187", "PHONE")]),
    ("My number is 480.555.0123 if anyone can help with groceries.", [("480.555.0123", "PHONE")]),
    ("Text me at +1 602 555 0166 about the furniture pickup.", [("+1 602 555 0166", "PHONE")]),
    ("contact 6025550171 anytime, need help with a form", [("6025550171", "PHONE")]),
    ("WhatsApp +91 98765 43210, I am in Tempe temporarily for studies.", [("+91 98765 43210", "PHONE")]),
    ("You can call me at four eight zero five five five zero one nine nine, evenings are best.", [("four eight zero five five five zero one nine nine", "PHONE")]),
    ("Call me on 602 five five five 0134 please, I need a tutor for my son.", [("602 five five five 0134", "PHONE")]),
    ("My phone is four-eight-zero, five-five-five, zero-one-four-eight. Need help with a resume.", [("four-eight-zero, five-five-five, zero-one-four-eight", "PHONE")]),
    ("ph: 480 555 0102 (landline), ask for Maria when you call", [("480 555 0102", "PHONE"), ("Maria", "NAME")]),
    # ---- emails ----
    ("Email me at rahul.sharma92@gmail.com with any volunteer who can tutor math.", [("rahul.sharma92@gmail.com", "EMAIL")]),
    ("my email is priya_nair@asu.edu, looking for help with a statement of purpose", [("priya_nair@asu.edu", "EMAIL")]),
    ("reach me at john dot miller at gmail dot com if you can help move boxes", [("john dot miller at gmail dot com", "EMAIL")]),
    ("send details to sarah.k@outlook.com or sarahk.work@yahoo.com", [("sarah.k@outlook.com", "EMAIL"), ("sarahk.work@yahoo.com", "EMAIL")]),
    # ---- addresses ----
    ("Please come to 742 Evergreen Terrace, Tempe, AZ 85281 to pick up the donated couch.", [("742 Evergreen Terrace, Tempe, AZ 85281", "ADDRESS")]),
    ("I live at 1900 E Apache Blvd Apt 214 and need help carrying groceries up.", [("1900 E Apache Blvd Apt 214", "ADDRESS")]),
    ("Pickup from 55 N Mill Ave, unit 3B. The items are in the garage.", [("55 N Mill Ave, unit 3B", "ADDRESS")]),
    ("My house is on 12 Oak Lane near the park, the blue door. Need yard cleanup.", [("12 Oak Lane", "ADDRESS")]),
    ("Send the paperwork to P.O. Box 4471, Mesa AZ 85201", [("P.O. Box 4471, Mesa AZ 85201", "ADDRESS")]),
    ("I live at four hundred twelve West Elm Street and the stairs are hard for me.", [("four hundred twelve West Elm Street", "ADDRESS")]),
    # ---- ID numbers ----
    ("Need help with my tax form, my SSN is 123-45-6789 in case the volunteer needs it.", [("123-45-6789", "ID")]),
    ("Aadhaar 2345 6789 0123 needed for the scholarship form help", [("2345 6789 0123", "ID")]),
    ("My card 4111 1111 1111 1111 was declined at the pharmacy, need help with the bill", [("4111 1111 1111 1111", "CARD")]),
    ("Passport number K1234567 expires soon, need renewal guidance", [("K1234567", "ID")]),
    # ---- names (English + non-English) ----
    ("Hi, my name is Priya Venkataraman and I need help filling out a Medicaid renewal.", [("Priya Venkataraman", "NAME")]),
    ("This is Wei Zhang. My mother needs a translator for her doctor visit (Mandarin).", [("Wei Zhang", "NAME")]),
    ("I'm Fatima Al-Mansouri, new to the area and need help finding a halal food pantry.", [("Fatima Al-Mansouri", "NAME")]),
    ("my name is jose hernandez, no tengo transporte para mi cita", [("jose hernandez", "NAME")]),
    ("Mi nombre es María Guadalupe Ramírez y necesito ayuda con la renta.", [("María Guadalupe Ramírez", "NAME")]),
    ("Please help Nguyen Thi Lan, an elderly neighbor, with grocery delivery.", [("Nguyen Thi Lan", "NAME")]),
    ("My neighbor Mrs. Okafor has been unable to leave her home since her surgery.", [("Mrs. Okafor", "NAME")]),
    ("Ask for Dmitri Volkov at the front desk, he knows about my case.", [("Dmitri Volkov", "NAME")]),
    ("Aarav Deshmukh is the point of contact for my child's tutoring sessions.", [("Aarav Deshmukh", "NAME")]),
    ("My son Kwame needs a ride to school every morning this week.", [("Kwame", "NAME")]),
    ("Hello, I am Anil Poojari and I need help reading and answering my mail.", [("Anil Poojari", "NAME")]),
    ("Rashmi here - need help with a resume review before Friday.", [("Rashmi", "NAME")]),
    ("माझे नाव सुनीता पाटील आहे, मला घरभाडे भरण्यासाठी मदत हवी आहे.", [("सुनीता पाटील", "NAME")]),
    ("제 이름은 김민준입니다. 병원까지 태워주실 분 찾습니다.", [("김민준", "NAME")]),
    # ---- combinations ----
    ("I'm Tomasz Kowalski, call (480) 555-0155 or email tomasz.k@gmail.com. I live at 88 W University Dr.",
     [("Tomasz Kowalski", "NAME"), ("(480) 555-0155", "PHONE"), ("tomasz.k@gmail.com", "EMAIL"), ("88 W University Dr", "ADDRESS")]),
    ("Contact my daughter Aisha Rahman at 602-555-0190 about the appointment.", [("Aisha Rahman", "NAME"), ("602-555-0190", "PHONE")]),
    ("Hi it's Li Na, I'm at Unit 2006, 301 Palm Court and need help with a broken heater.", [("Li Na", "NAME"), ("301 Palm Court", "ADDRESS")]),
    ("Name: Oluwaseun Adeyemi, DOB 03/14/1961. Needs help with pharmacy pickup.", [("Oluwaseun Adeyemi", "NAME"), ("03/14/1961", "DOB")]),
    # ---- clean texts (no personal detail) ----
    ("Need a ride to dialysis on Friday morning, around 9:30 am, round trip.", []),
    ("Looking for help moving a couch, about 150 pounds, from a second floor apartment.", []),
    ("Rent is $1,450 this month and I'm short by $320.", []),
    ("My landlord gave a 30 day notice on Nov 12, need legal aid information.", []),
    ("Requesting grocery delivery for a family of 5, no peanuts please.", []),
    ("Need tutoring in Algebra 2 for my 10th grade daughter, twice a week.", []),
    ("Looking for a volunteer who speaks Spanish or Vietnamese to translate at a clinic visit.", []),
    ("Storm damage to the roof, tarp needed before Monday. Home Depot quote was $890.", []),
    ("Help with job application at Walmart and Amazon, need resume formatting.", []),
    ("Looking for transportation from Tempe to Phoenix Sky Harbor on Dec 3rd at 6 am.", []),
    ("Need winter coats for 3 kids, sizes 6, 8 and 10.", []),
    ("Can someone explain the Medicaid renewal letter I received? Some of the terms are confusing.", []),
    ("Senior needs help setting up a smartphone and video calls with grandchildren.", []),
    ("Request REQ-000123 was not updated, please check the status.", []),
    ("Our food pantry on Saturday served 212 households, we need 40 more volunteers.", []),
    ("Need a wheelchair ramp, 3 steps, about 24 inches high.", []),
    ("Please help with a bus pass for the 72 route to get to work at 7:00.", []),
    ("Help writing a letter to the Housing Authority about a broken heater since 12/01/2026.", []),
    ("Mondays and Wednesdays after 4 pm work best. Anyone from Arizona State University or Mesa Community College is welcome.", []),
    ("Need help understanding Social Security benefits, I'm not sure how to apply online.", []),
    ("Help needed with a Chinese to English translation of school forms.", []),
    ("I need Help with Rent. The Mayor's office said funds open in January.", []),
]

HELDOUT = [
    ("Hello. I'm Chinedu Okonkwo. I recently lost my job and need help with bills.", [("Chinedu Okonkwo", "NAME")]),
    ("call my cell 480 555 0111 any time after lunch", [("480 555 0111", "PHONE")]),
    ("you can email jmartinez77@hotmail.com with questions", [("jmartinez77@hotmail.com", "EMAIL")]),
    ("We live at 3015 S Rural Rd, Apt 5, Tempe and need a car seat installed.", [("3015 S Rural Rd, Apt 5", "ADDRESS")]),
    ("My phone number: (602)555-0128. Please text first.", [("(602)555-0128", "PHONE")]),
    ("Please contact Ms. Priyanka Joshi regarding the school forms.", [("Ms. Priyanka Joshi", "NAME")]),
    ("my aadhaar is 3456-7890-1234, needed for a subsidy application", [("3456-7890-1234", "ID")]),
    ("Reach me at five five five, one two three four after 6 pm", [("five five five, one two three four", "PHONE")]),
    ("Soy Carlos Mendoza, necesito comida para mi familia esta semana.", [("Carlos Mendoza", "NAME")]),
    ("Khadija Bint Rashid asked me to submit this for her, she can't use the app.", [("Khadija Bint Rashid", "NAME")]),
    ("Send the receipt to ahmed.ali [at] gmail [dot] com please", [("ahmed.ali [at] gmail [dot] com", "EMAIL")]),
    ("Dropoff at 7421 W Camelback Road Phoenix please, before noon.", [("7421 W Camelback Road Phoenix", "ADDRESS")]),
    ("Need help with a computer for school. Thanks, Elena Petrova", [("Elena Petrova", "NAME")]),
    ("My daughter Mei Lin and I need a ride to the clinic on Tuesday.", [("Mei Lin", "NAME")]),
    # clean
    ("Need help installing a smoke detector, the ceiling is about 10 feet high.", []),
    ("Does anyone have a used laptop for a high school student? Windows is fine.", []),
    ("Looking for a ride on Tuesday at 8:15 to the DMV on Baseline Road.", []),
    ("Need diapers size 4, about 3 packs, and baby formula.", []),
    ("Family of four needs help with an electric bill of $212 due Dec 5.", []),
    ("Seeking a Hindi speaking volunteer for a bank visit on Thursday.", []),
]
