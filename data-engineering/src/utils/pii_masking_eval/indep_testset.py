"""Independent labelled test set for issue #585.

Written without reference to the detector implementation in PR #715, in the
voice of people asking a nonprofit for help. Same format as their testset.py:
    (text, [(pii_substring, type), ...])    empty list => clean
All names, numbers, emails and addresses are invented.
"""

ITEMS = [
    # ---------------- phones ----------------
    ("Can someone call me back on 4805550198? I need help filling out a Medicaid form.", [("4805550198", "PHONE")]),
    ("best number is (602) 555-0144, I work nights so mornings are fine", [("(602) 555-0144", "PHONE")]),
    ("Reach my daughter instead, 480 555 0176, she speaks better English than me.", [("480 555 0176", "PHONE")]),
    ("Cell: 623-555-0119. Looking for a used stroller for a newborn.", [("623-555-0119", "PHONE")]),
    ("call or text 1-480-555-0163, either is fine", [("1-480-555-0163", "PHONE")]),
    ("my number is nine two eight five five five zero one two two", [("nine two eight five five five zero one two two", "PHONE")]),
    ("You can get me on +1 (480) 555-0187 during the day.", [("+1 (480) 555-0187", "PHONE")]),
    ("Phone 4 8 0 5 5 5 0 1 7 7, I do not have email.", [("4 8 0 5 5 5 0 1 7 7", "PHONE")]),
    ("Text 602.555.0191, I don't answer unknown calls.", [("602.555.0191", "PHONE")]),
    ("Leave a message on 480-555-0108 and I will call back in the evening.", [("480-555-0108", "PHONE")]),

    # ---------------- emails ----------------
    ("Please email lucia.ramos@gmail.com, I check it twice a day.", [("lucia.ramos@gmail.com", "EMAIL")]),
    ("write to me: tdang91@yahoo.com about the bus pass", [("tdang91@yahoo.com", "EMAIL")]),
    ("my email is ahmed [at] hotmail [dot] com if that is easier", [("ahmed [at] hotmail [dot] com", "EMAIL")]),
    ("contact k.obrien@asu.edu for the tutoring slot on Saturday", [("k.obrien@asu.edu", "EMAIL")]),
    ("send to grace.mensah@outlook.com, I check it daily", [("grace.mensah@outlook.com", "EMAIL")]),

    # ---------------- names WITH a cue ----------------
    ("My name is Oluwaseun Adeyemi and I need winter clothes for my kids.", [("Oluwaseun Adeyemi", "NAME")]),
    ("This is Tran Van Minh, I called last week about the wheelchair ramp.", [("Tran Van Minh", "NAME")]),
    ("Mi nombre es Rosa Delgado, necesito ayuda con la renta.", [("Rosa Delgado", "NAME")]),
    ("my name is kwame boateng, i am looking for a job reference", [("kwame boateng", "NAME")]),
    ("Thanks, Dmitri Volkov", [("Dmitri Volkov", "NAME")]),
    ("मेरा नाम सुनीता शर्मा है, मुझे राशन की मदद चाहिए।", [("सुनीता शर्मा", "NAME")]),

    # ---------------- names with NO cue (very common in real requests) ----------------
    ("Fatima Zahra cannot walk to the clinic and needs a ride Tuesday.", [("Fatima Zahra", "NAME")]),
    ("Nguyen Thi Hoa lost her job and needs food assistance this month.", [("Nguyen Thi Hoa", "NAME")]),
    ("Could someone tutor Priyanka in algebra on weekends?", [("Priyanka", "NAME")]),
    ("Jorge Villanueva is moving out on the 30th and has no truck.", [("Jorge Villanueva", "NAME")]),
    ("The wheelchair is for Bernice Okafor, she is 82 and lives alone.", [("Bernice Okafor", "NAME")]),
    ("Hassan needs a winter coat, size medium.", [("Hassan", "NAME")]),
    ("Chen Wei's apartment flooded and he lost his documents.", [("Chen Wei", "NAME")]),
    ("Looking for someone to sit with Margarethe Lindqvist while I work nights.", [("Margarethe Lindqvist", "NAME")]),
    ("Aditi and Rohan both need school supplies before Monday.", [("Aditi", "NAME"), ("Rohan", "NAME")]),

    # ---------------- addresses ----------------
    ("I'm at 3421 S Rural Rd, Tempe AZ 85282. The couch is on the porch.", [("3421 S Rural Rd, Tempe AZ 85282", "ADDRESS")]),
    ("Delivery to 88 West Baseline Road, apartment 7.", [("88 West Baseline Road, apartment 7", "ADDRESS")]),
    ("We live near 1200 N Scottsdale Rd but the gate needs a code.", [("1200 N Scottsdale Rd", "ADDRESS")]),
    ("PO Box 4471, Mesa AZ 85201 is where mail should go.", [("PO Box 4471, Mesa AZ 85201", "ADDRESS")]),
    ("My place is at twelve forty one East Broadway, the grey building.", [("twelve forty one East Broadway", "ADDRESS")]),

    # ---------------- id numbers ----------------
    ("My SSN is 412-55-9087, do I need it for the application?", [("412-55-9087", "ID")]),
    ("Aadhaar 4521 8899 1234, I just moved here from India.", [("4521 8899 1234", "ID")]),
    ("passport number X1234567 if that helps with the paperwork", [("X1234567", "ID")]),
    ("Is it safe to share a card here? It is 4111 1111 1111 1111.", [("4111 1111 1111 1111", "CARD")]),
    ("DOB: 03/14/1978, applying for senior services.", [("03/14/1978", "DOB")]),

    # ---------------- clean ----------------
    ("I need help with my Social Security application, no idea where to start.", []),
    ("Looking for a volunteer who speaks Mandarin to help at the clinic Thursday.", []),
    ("Our rent went up by $340 this month and we are short.", []),
    ("Request ID 00-123-456 was closed but my issue is not resolved.", []),
    ("Can anyone donate a microwave? Ours died last week.", []),
    ("The food bank on Baseline closes at 4pm, is there a later one?", []),
    ("I work at Walmart on weekends and need childcare Saturday mornings.", []),
    ("Need a ride to the airport on December 3rd at 6am.", []),
    ("Thanksgiving dinner for four, if anyone has extra.", []),
    ("Contact Center said to file here instead.", []),
    ("Help Wanted signs are everywhere but nobody calls back.", []),
    ("I'm looking for English classes near Mill Avenue.", []),
    ("My Medicaid renewal is due but the website keeps timing out.", []),
    ("Call Center hours are 9 to 5, that does not work for me.", []),
    ("Five people in the household, two are under ten.", []),
    ("We need about 20 blankets for the shelter on Apache.", []),
    ("Is there a free legal clinic in Maricopa County?", []),
    ("The appointment is at 2:30 on Tuesday the 14th.", []),
    ("Lost my job in March, still looking for anything.", []),
    ("My son is in third grade and needs a backpack.", []),
]

DEV = []
HELDOUT = ITEMS
