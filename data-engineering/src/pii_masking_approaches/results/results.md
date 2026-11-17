# Results: PII masking approaches (#585), main set

Test set: 72 requests (50 with personal details, 22 without), 73 labelled details. Users-table names: 408 name parts, loaded in 8.9 ms.

| Approach | Caught | Partly | Missed | PII requests fully cleaned | Clean requests wrongly redacted | False-positive redactions | Time per request |
|---|---|---|---|---|---|---|---|
| 1. Pipeline patterns only | 22 (30.1%) | 0 | 51 | 9/50 | 1/22 | 1 | 0.0062 ms |
| 2. Pipeline + users-table lookup | 42 (57.5%) | 5 | 26 | 25/50 | 4/22 | 6 | 0.0113 ms |
| 3. Pipeline + Amazon Comprehend | not run: no AWS access yet (run with --comprehend) | | | | | | |
| 4. Improved rules (patterns + users names + name cues) | 71 (97.3%) | 0 | 2 | 49/50 | 0/22 | 0 | 0.0546 ms |
| 5. Improved patterns + spaCy small model (reference) | 66 (90.4%) | 1 | 6 | 43/50 | 1/22 | 6 | 4.2217 ms |

## Caught per type

| Approach | NAME | PHONE | EMAIL | ADDRESS | ID | CARD | URL | DOB |
|---|---|---|---|---|---|---|---|---|
| 1. Pipeline patterns only | 0/31 | 13/19 | 6/8 | 0/10 | 1/2 | 1/1 | 1/1 | 0/1 |
| 2. Pipeline + users-table lookup | 20/31 | 13/19 | 6/8 | 0/10 | 1/2 | 1/1 | 1/1 | 0/1 |
| 4. Improved rules (patterns + users names + name cues) | 29/31 | 19/19 | 8/8 | 10/10 | 2/2 | 1/1 | 1/1 | 1/1 |
| 5. Improved patterns + spaCy small model (reference) | 24/31 | 19/19 | 8/8 | 10/10 | 2/2 | 1/1 | 1/1 | 1/1 |

## Not fully caught

- **1. Pipeline patterns only**: P04 NAME (missed), P05 ADDRESS (missed), P06 NAME (missed), P06 NAME (missed), P07 PHONE (missed), P08 NAME (missed), P09 NAME (missed), P10 EMAIL (missed), P11 ADDRESS (missed), P12 NAME (missed), P15 NAME (missed), P17 ADDRESS (missed), P17 NAME (missed), P18 NAME (missed), P19 PHONE (missed), P20 NAME (missed), P20 PHONE (missed), P21 NAME (missed), P22 NAME (missed), P23 ADDRESS (missed), P24 NAME (missed), P25 NAME (missed), P26 NAME (missed), P28 NAME (missed), P29 ADDRESS (missed), P30 NAME (missed), P30 DOB (missed), P31 PHONE (missed), P32 NAME (missed), P32 NAME (missed), P34 ADDRESS (missed), P34 NAME (missed), P35 NAME (missed), P36 PHONE (missed), P37 ID (missed), P38 NAME (missed), P39 NAME (missed), P39 PHONE (missed), P40 NAME (missed), P41 NAME (missed), P42 ADDRESS (missed), P42 ADDRESS (missed), P43 ADDRESS (missed), P43 NAME (missed), P44 NAME (missed), P46 NAME (missed), P47 NAME (missed), P48 NAME (missed), P49 ADDRESS (missed), P49 NAME (missed), P50 EMAIL (missed)
- **2. Pipeline + users-table lookup**: P05 ADDRESS (missed), P06 NAME (missed), P07 PHONE (missed), P10 EMAIL (partly), P11 ADDRESS (missed), P17 ADDRESS (missed), P19 PHONE (missed), P20 PHONE (missed), P23 ADDRESS (missed), P29 ADDRESS (missed), P30 NAME (partly), P30 DOB (missed), P31 PHONE (missed), P32 NAME (missed), P32 NAME (missed), P34 ADDRESS (missed), P34 NAME (missed), P36 PHONE (missed), P37 ID (missed), P39 NAME (missed), P39 PHONE (missed), P40 NAME (missed), P41 NAME (missed), P42 ADDRESS (missed), P42 ADDRESS (missed), P43 ADDRESS (missed), P44 NAME (missed), P48 NAME (partly), P49 ADDRESS (missed), P49 NAME (partly), P50 EMAIL (partly)
- **4. Improved rules (patterns + users names + name cues)**: P32 NAME (missed), P32 NAME (missed)
- **5. Improved patterns + spaCy small model (reference)**: P09 NAME (missed), P25 NAME (partly), P28 NAME (missed), P32 NAME (missed), P39 NAME (missed), P40 NAME (missed), P44 NAME (missed)

## Clean requests wrongly redacted

- **1. Pipeline patterns only**: C21
- **2. Pipeline + users-table lookup**: C04, C06, C07, C21
- **4. Improved rules (patterns + users names + name cues)**: none
- **5. Improved patterns + spaCy small model (reference)**: C22

## Masked output per request

<details><summary>P01</summary>

- original: `Need groceries this week` / `We ran out of food. Please call me at 571-555-0142 after 5pm.`
- 1: `Need groceries this week` / `We ran out of food. Please call me at [PHONE] after 5pm.`
- 2: `Need groceries this week` / `We ran out of food. Please call me at [PHONE] after 5pm.`
- 4: `Need groceries this week` / `We ran out of food. Please call me at [PHONE] after 5pm.`
- 5: `Need groceries this week` / `We ran out of food. Please call me at [PHONE] after 5pm.`

</details>

<details><summary>P02</summary>

- original: `Ride to clinic` / `My appointment is Friday morning. Text me on (703) 555 0198 if you can drive.`
- 1: `Ride to clinic` / `My appointment is Friday morning. Text me on [PHONE] if you can drive.`
- 2: `Ride to clinic` / `My appointment is Friday morning. Text me on [PHONE] if you can drive.`
- 4: `Ride to clinic` / `My appointment is Friday morning. Text me on [PHONE] if you can drive.`
- 5: `Ride to clinic` / `My appointment is Friday morning. Text me on [PHONE] if you can drive.`

</details>

<details><summary>P03</summary>

- original: `Help moving furniture` / `Contact me at maria.gonzalez84@example.com, I'm free on weekends.`
- 1: `Help moving furniture` / `Contact me at [EMAIL], I'm free on weekends.`
- 2: `Help moving furniture` / `Contact me at [EMAIL], I'm free on weekends.`
- 4: `Help moving furniture` / `Contact me at [EMAIL], I'm free on weekends.`
- 5: `Help moving furniture` / `Contact me at [EMAIL], I'm free on weekends.`

</details>

<details><summary>P04</summary>

- original: `Food for my family` / `Hi, my name is Priya Venkataraman and we need rice and lentils for 4 people.`
- 1: `Food for my family` / `Hi, my name is Priya Venkataraman and we need rice and lentils for 4 people.`
- 2: `Food for my family` / `Hi, my name is [NAME] [NAME] and we need rice and lentils for 4 people.`
- 4: `Food for my family` / `Hi, my name is [NAME] and we need rice and lentils for 4 people.`
- 5: `Food for my family` / `Hi, my name is [NAME] and we need rice and lentils for 4 people.`

</details>

<details><summary>P05</summary>

- original: `Wheelchair ramp` / `I live at 1428 Elm Street, Apt 3B, Reston VA 20190 and need a small ramp built.`
- 1: `Wheelchair ramp` / `I live at 1428 Elm Street, Apt 3B, Reston VA 20190 and need a small ramp built.`
- 2: `Wheelchair ramp` / `I live at 1428 Elm Street, Apt 3B, Reston VA 20190 and need a small ramp built.`
- 4: `Wheelchair ramp` / `I live at [ADDRESS], Reston VA 20190 and need a small ramp built.`
- 5: `Wheelchair ramp` / `I live at [ADDRESS], Reston VA 20190 and need a small ramp built.`

</details>

<details><summary>P06</summary>

- original: `Tutoring for my son` / `My son Mateo needs help with algebra. You can reach my husband Wei Zhang at +1 202 555 0175.`
- 1: `Tutoring for my son` / `My son Mateo needs help with algebra. You can reach my husband Wei Zhang at [PHONE].`
- 2: `Tutoring for my son` / `My son Mateo needs help with algebra. You can reach my husband [NAME] [NAME] at [PHONE].`
- 4: `Tutoring for my son` / `My son [NAME] needs help with algebra. You can reach my husband [NAME] at [PHONE].`
- 5: `Tutoring for my son` / `My son [NAME] needs help with algebra. You can reach my husband [NAME] at [PHONE].`

</details>

<details><summary>P07</summary>

- original: `Medicine pickup` / `Please pick up my prescription. My phone number is five seven one, five five five, zero one nine three.`
- 1: `Medicine pickup` / `Please pick up my prescription. My phone number is five seven one, five five five, zero one nine three.`
- 2: `Medicine pickup` / `Please pick up my prescription. My phone number is five seven one, five five five, zero one nine three.`
- 4: `Medicine pickup` / `Please pick up my prescription. My phone number is [PHONE].`
- 5: `Medicine pickup` / `Please pick up my prescription. My phone number is [PHONE].`

</details>

<details><summary>P08</summary>

- original: `Rent help` / `I am Oluwaseun Adeyemi, a single mother of two, and I am short on rent this month.`
- 1: `Rent help` / `I am Oluwaseun Adeyemi, a single mother of two, and I am short on rent this month.`
- 2: `Rent help` / `I am [NAME] [NAME], a single mother of two, and I am short on rent this month.`
- 4: `Rent help` / `I am [NAME], a single mother of two, and I am short on rent this month.`
- 5: `Rent help` / `I am [NAME], a single mother of two, and I am short on rent this month.`

</details>

<details><summary>P09</summary>

- original: `Phone call needed` / `Call 9876543210 (India) and ask for Lakshmi.`
- 1: `Phone call needed` / `Call [PHONE] (India) and ask for Lakshmi.`
- 2: `Phone call needed` / `Call [PHONE] (India) and ask for [NAME].`
- 4: `Phone call needed` / `Call [PHONE] (India) and ask for [NAME].`
- 5: `Phone call needed` / `Call [PHONE] (India) and ask for Lakshmi.`

</details>

<details><summary>P10</summary>

- original: `Help with groceries` / `Email: fatima dot alsayed at gmail dot com`
- 1: `Help with groceries` / `Email: fatima dot alsayed at gmail dot com`
- 2: `Help with groceries` / `Email: [NAME] dot alsayed at gmail dot com`
- 4: `Help with groceries` / `Email: [EMAIL]`
- 5: `Help with groceries` / `[NAME]: [EMAIL]`

</details>

<details><summary>P11</summary>

- original: `Winter clothes` / `Drop off at 77 Maple Ave, Herndon. Ring the bell twice.`
- 1: `Winter clothes` / `Drop off at 77 Maple Ave, Herndon. Ring the bell twice.`
- 2: `Winter clothes` / `Drop off at 77 Maple Ave, Herndon. Ring the bell twice.`
- 4: `Winter clothes` / `Drop off at [ADDRESS], Herndon. Ring the bell twice.`
- 5: `Winter clothes` / `[NAME] off at [ADDRESS], [NAME]. Ring the bell twice.`

</details>

<details><summary>P12</summary>

- original: `Translation help` / `Necesito ayuda con documentos. Me llamo José Hernández, mi teléfono es 555-201-7788.`
- 1: `Translation help` / `Necesito ayuda con documentos. Me llamo José Hernández, mi teléfono es [PHONE].`
- 2: `Translation help` / `Necesito ayuda con documentos. Me llamo [NAME] [NAME], mi teléfono es [PHONE].`
- 4: `Translation help` / `Necesito ayuda con documentos. Me llamo [NAME], mi teléfono es [PHONE].`
- 5: `Translation help` / `[NAME] ayuda con documentos. Me llamo [NAME], mi teléfono es [PHONE].`

</details>

<details><summary>P13</summary>

- original: `Job application help` / `Please review my resume. My SSN is 123-45-6789 if the form needs it.`
- 1: `Job application help` / `Please review my resume. My SSN is [SSN] if the form needs it.`
- 2: `Job application help` / `Please review my resume. My SSN is [SSN] if the form needs it.`
- 4: `Job application help` / `Please review my resume. My SSN is [SSN] if the form needs it.`
- 5: `Job application help` / `Please review my resume. My SSN is [SSN] if the form needs it.`

</details>

<details><summary>P14</summary>

- original: `Paying a bill` / `Can someone pay my electricity bill? Card 4111 1111 1111 1111 exp 09/27.`
- 1: `Paying a bill` / `Can someone pay my electricity bill? Card [CARD]exp 09/27.`
- 2: `Paying a bill` / `Can someone pay my electricity bill? Card [CARD]exp 09/27.`
- 4: `Paying a bill` / `Can someone pay my electricity bill? Card [CARD] exp 09/27.`
- 5: `Paying a bill` / `Can someone pay my electricity bill? Card [CARD] exp 09/27.`

</details>

<details><summary>P15</summary>

- original: `Elderly neighbor check-in` / `My neighbour Dmitri Volkov is 82 and lives alone; his number is 703.555.0123.`
- 1: `Elderly neighbor check-in` / `My neighbour Dmitri Volkov is 82 and lives alone; his number is [PHONE].`
- 2: `Elderly neighbor check-in` / `My neighbour [NAME] [NAME] is 82 and lives alone; his number is [PHONE].`
- 4: `Elderly neighbor check-in` / `My neighbour [NAME] is 82 and lives alone; his number is [PHONE].`
- 5: `Elderly neighbor check-in` / `My neighbour [NAME] is 82 and lives alone; his number is [PHONE].`

</details>

<details><summary>P16</summary>

- original: `Groceries` / `aiko.tanaka@example.org - please deliver Tuesday`
- 1: `Groceries` / `[EMAIL] - please deliver Tuesday`
- 2: `Groceries` / `[EMAIL] - please deliver Tuesday`
- 4: `Groceries` / `[EMAIL] - please deliver Tuesday`
- 5: `Groceries` / `[EMAIL] - please deliver Tuesday`

</details>

<details><summary>P17</summary>

- original: `Need a ride` / `Pickup from 3300 Fairfax Drive, Arlington around 9. Ask for Mr. Mehta.`
- 1: `Need a ride` / `Pickup from 3300 Fairfax Drive, Arlington around 9. Ask for Mr. Mehta.`
- 2: `Need a ride` / `Pickup from 3300 Fairfax Drive, Arlington around 9. Ask for Mr. [NAME].`
- 4: `Need a ride` / `Pickup from [ADDRESS], Arlington around 9. Ask for Mr. [NAME].`
- 5: `Need a ride` / `Pickup from [ADDRESS], Arlington around 9. Ask for Mr. [NAME].`

</details>

<details><summary>P18</summary>

- original: `Help for my mom` / `My mother Siobhan O'Connor needs someone to help her with shopping.`
- 1: `Help for my mom` / `My mother Siobhan O'Connor needs someone to help her with shopping.`
- 2: `Help for my mom` / `My mother [NAME] [NAME] needs someone to help her with shopping.`
- 4: `Help for my mom` / `My mother [NAME] needs someone to help her with shopping.`
- 5: `Help for my mom` / `My mother [NAME] needs someone to help her with shopping.`

</details>

<details><summary>P19</summary>

- original: `Car seat` / `WhatsApp +91 98450 12345 anytime.`
- 1: `Car seat` / `WhatsApp +91 98450 12345 anytime.`
- 2: `Car seat` / `WhatsApp +91 98450 12345 anytime.`
- 4: `Car seat` / `WhatsApp [PHONE] anytime.`
- 5: `Car seat` / `WhatsApp [PHONE] anytime.`

</details>

<details><summary>P20</summary>

- original: `Cooking help` / `Contact Lan Nguyen on 0412 345 678 (Australia).`
- 1: `Cooking help` / `Contact Lan Nguyen on 0412 345 678 (Australia).`
- 2: `Cooking help` / `Contact [NAME] [NAME] on 0412 345 678 (Australia).`
- 4: `Cooking help` / `Contact [NAME] on [PHONE] (Australia).`
- 5: `Cooking help` / `Contact [NAME] on [PHONE] (Australia).`

</details>

<details><summary>P21</summary>

- original: `Laptop for school` / `My daughter Zainab Okafor needs a laptop for online classes.`
- 1: `Laptop for school` / `My daughter Zainab Okafor needs a laptop for online classes.`
- 2: `Laptop for school` / `My daughter [NAME] [NAME] needs a laptop for online classes.`
- 4: `Laptop for school` / `My daughter [NAME] needs a laptop for online classes.`
- 5: `Laptop for school` / `My daughter [NAME] needs a laptop for online classes.`

</details>

<details><summary>P22</summary>

- original: `Tax forms` / `Hello, this is Tomasz Kowalski. I need help filing taxes. Email tkowalski@example.net.`
- 1: `Tax forms` / `Hello, this is Tomasz Kowalski. I need help filing taxes. Email [EMAIL]`
- 2: `Tax forms` / `Hello, this is [NAME] [NAME]. I need help filing taxes. Email [EMAIL]`
- 4: `Tax forms` / `Hello, this is [NAME]. I need help filing taxes. Email [EMAIL].`
- 5: `Tax forms` / `Hello, this is [NAME]. I need help filing taxes. Email [EMAIL].`

</details>

<details><summary>P23</summary>

- original: `Food bank directions` / `I'm at 15 Rue de la Paix, call me 0612345678.`
- 1: `Food bank directions` / `I'm at 15 Rue de la Paix, call me [PHONE].`
- 2: `Food bank directions` / `I'm at 15 Rue de la Paix, call me [PHONE].`
- 4: `Food bank directions` / `I'm at [ADDRESS], call me [PHONE].`
- 5: `Food bank directions` / `I'm at [ADDRESS], call me [PHONE].`

</details>

<details><summary>P24</summary>

- original: `Help with forms` / `My name is grace kim and I need help with a housing application.`
- 1: `Help with forms` / `My name is grace kim and I need help with a housing application.`
- 2: `Help with forms` / `My name is [NAME] [NAME] and I need help with a housing application.`
- 4: `Help with forms` / `My name is [NAME] and I need help with a housing application.`
- 5: `Help with forms` / `My name is [NAME] and I need help with a housing application.`

</details>

<details><summary>P25</summary>

- original: `Dog walking` / `Hope Williams here, recovering from surgery, need someone to walk my dog.`
- 1: `Dog walking` / `Hope Williams here, recovering from surgery, need someone to walk my dog.`
- 2: `Dog walking` / `[NAME] [NAME] here, recovering from surgery, need someone to walk my dog.`
- 4: `Dog walking` / `[NAME] here, recovering from surgery, need someone to walk my dog.`
- 5: `Dog walking` / `Hope [NAME] here, recovering from surgery, need someone to walk my dog.`

</details>

<details><summary>P26</summary>

- original: `Diapers` / `Please call May Lin at 571 555 0110.`
- 1: `Diapers` / `Please call May Lin at [PHONE].`
- 2: `Diapers` / `Please call [NAME] [NAME] at [PHONE].`
- 4: `Diapers` / `Please call [NAME] at [PHONE].`
- 5: `Diapers` / `Please call [NAME] at [PHONE].`

</details>

<details><summary>P27</summary>

- original: `Ride to court` / `You can find me on facebook https://facebook.com/rahul.mehta.77`
- 1: `Ride to court` / `You can find me on facebook [URL]`
- 2: `Ride to court` / `You can find me on facebook [URL]`
- 4: `Ride to court` / `You can find me on facebook [URL]`
- 5: `Ride to court` / `You can find me on facebook [URL]`

</details>

<details><summary>P28</summary>

- original: `Emergency food` / `Text 2025550147. Thanks, Maria`
- 1: `Emergency food` / `Text [PHONE]. Thanks, Maria`
- 2: `Emergency food` / `Text [PHONE]. Thanks, [NAME]`
- 4: `Emergency food` / `Text [PHONE]. Thanks, [NAME]`
- 5: `Emergency food` / `Text [PHONE]. Thanks, Maria`

</details>

<details><summary>P29</summary>

- original: `Furniture` / `Address: 9 Birch Ct, Leesburg VA 20175`
- 1: `Furniture` / `Address: 9 Birch Ct, Leesburg VA 20175`
- 2: `Furniture` / `Address: 9 Birch Ct, Leesburg VA 20175`
- 4: `Furniture` / `Address: [ADDRESS], Leesburg VA 20175`
- 5: `Furniture` / `Address: [ADDRESS], Leesburg VA 20175`

</details>

<details><summary>P30</summary>

- original: `Medical transport` / `Patient: Ahmed Hassan, DOB 03/14/1958, needs transport to dialysis.`
- 1: `Medical transport` / `Patient: Ahmed Hassan, DOB 03/14/1958, needs transport to dialysis.`
- 2: `Medical transport` / `Patient: [NAME] Hassan, DOB 03/14/1958, needs transport to dialysis.`
- 4: `Medical transport` / `Patient: [NAME], DOB [DOB], needs transport to dialysis.`
- 5: `Medical transport` / `Patient: [NAME], DOB [DOB], needs transport to dialysis.`

</details>

<details><summary>P31</summary>

- original: `Phone number` / `my number is 7 0 3 5 5 5 0 1 6 6`
- 1: `Phone number` / `my number is 7 0 3 5 5 5 0 1 6 6`
- 2: `Phone number` / `my number is 7 0 3 5 5 5 0 1 6 6`
- 4: `Phone number` / `my number is [PHONE]`
- 5: `Phone number` / `my number is [PHONE]`

</details>

<details><summary>P32</summary>

- original: `Help for Ravi` / `Ravi Shankar needs grocery delivery, he is diabetic.`
- 1: `Help for Ravi` / `Ravi Shankar needs grocery delivery, he is diabetic.`
- 2: `Help for Ravi` / `Ravi Shankar needs grocery delivery, he is diabetic.`
- 4: `Help for Ravi` / `Ravi Shankar needs grocery delivery, he is diabetic.`
- 5: `Help for Ravi` / `[NAME] needs grocery delivery, he is diabetic.`

</details>

<details><summary>P33</summary>

- original: `Groceries` / `Contact: chen.wei@example.com or 571-555-0199 ext 4`
- 1: `Groceries` / `Contact: [EMAIL] or [PHONE] ext 4`
- 2: `Groceries` / `Contact: [EMAIL] or [PHONE] ext 4`
- 4: `Groceries` / `Contact: [EMAIL] or [PHONE] ext 4`
- 5: `Groceries` / `Contact: [EMAIL] or [PHONE] ext 4`

</details>

<details><summary>P34</summary>

- original: `Shelter` / `I'm staying at my cousin's place, 210 Oak Lane Unit 5. Name is Kwame Mensah.`
- 1: `Shelter` / `I'm staying at my cousin's place, 210 Oak Lane Unit 5. Name is Kwame Mensah.`
- 2: `Shelter` / `I'm staying at my cousin's place, 210 Oak Lane Unit 5. Name is Kwame Mensah.`
- 4: `Shelter` / `I'm staying at my cousin's place, [ADDRESS]. Name is [NAME].`
- 5: `Shelter` / `I'm staying at my cousin's place, [ADDRESS]. Name is [NAME].`

</details>

<details><summary>P35</summary>

- original: `School supplies` / `Ask Ms. Iyer at the front desk, she knows my situation.`
- 1: `School supplies` / `Ask Ms. Iyer at the front desk, she knows my situation.`
- 2: `School supplies` / `Ask Ms. [NAME] at the front desk, she knows my situation.`
- 4: `School supplies` / `Ask Ms. [NAME] at the front desk, she knows my situation.`
- 5: `School supplies` / `Ask Ms. [NAME] at the front desk, she knows my situation.`

</details>

<details><summary>P36</summary>

- original: `Help needed` / `Please call nine eight seven six five four three two one zero.`
- 1: `Help needed` / `Please call nine eight seven six five four three two one zero.`
- 2: `Help needed` / `Please call nine eight seven six five four three two one zero.`
- 4: `Help needed` / `Please call [PHONE].`
- 5: `Help needed` / `Please call [PHONE].`

</details>

<details><summary>P37</summary>

- original: `Passport renewal` / `My passport number is K1234567, need help booking an appointment.`
- 1: `Passport renewal` / `My passport number is K1234567, need help booking an appointment.`
- 2: `Passport renewal` / `My passport number is K1234567, need help booking an appointment.`
- 4: `Passport renewal` / `My passport number is [ID], need help booking an appointment.`
- 5: `Passport renewal` / `My passport number is [ID], need help booking an appointment.`

</details>

<details><summary>P38</summary>

- original: `Groceries for Mrs. Gonzalez` / `She lives on the second floor and cannot carry bags.`
- 1: `Groceries for Mrs. Gonzalez` / `She lives on the second floor and cannot carry bags.`
- 2: `Groceries for Mrs. [NAME]` / `She lives on the second floor and cannot carry bags.`
- 4: `Groceries for Mrs. [NAME]` / `She lives on the second floor and cannot carry bags.`
- 5: `Groceries for Mrs. [NAME]` / `She lives on the second floor and cannot carry bags.`

</details>

<details><summary>P39</summary>

- original: `Babysitter` / `Reach me (Aisha) on +44 7700 900123.`
- 1: `Babysitter` / `Reach me (Aisha) on +44 7700 900123.`
- 2: `Babysitter` / `Reach me (Aisha) on +44 7700 900123.`
- 4: `Babysitter` / `Reach me ([NAME]) on [PHONE].`
- 5: `[NAME]` / `Reach me (Aisha) on [PHONE].`

</details>

<details><summary>P40</summary>

- original: `Food` / `मेरा नाम सुनीता शर्मा है, I need food for my kids.`
- 1: `Food` / `मेरा नाम सुनीता शर्मा है, I need food for my kids.`
- 2: `Food` / `मेरा नाम सुनीता शर्मा है, I need food for my kids.`
- 4: `Food` / `मेरा नाम [NAME] है, I need food for my kids.`
- 5: `Food` / `मेरा नाम सुनीता शर्मा है, I need food for my kids.`

</details>

<details><summary>P41</summary>

- original: `Water bill` / `Account holder: Juan Pablo Ortiz. Please help with $120.`
- 1: `Water bill` / `Account holder: Juan Pablo Ortiz. Please help with $120.`
- 2: `Water bill` / `Account holder: Juan Pablo Ortiz. Please help with $120.`
- 4: `Water bill` / `Account holder: [NAME]. Please help with $120.`
- 5: `Water bill` / `Account holder: [NAME]. Please help with $120.`

</details>

<details><summary>P42</summary>

- original: `Move help` / `Moving from 500 King St to 12 Queen Street on Saturday.`
- 1: `Move help` / `Moving from 500 King St to 12 Queen Street on Saturday.`
- 2: `Move help` / `Moving from 500 King St to 12 Queen Street on Saturday.`
- 4: `Move help` / `Moving from [ADDRESS] to [ADDRESS] on Saturday.`
- 5: `Move help` / `Moving from [ADDRESS] to [ADDRESS] on Saturday.`

</details>

<details><summary>P43</summary>

- original: `Ride` / `Pick me up near 8100 Lee Hwy, my name is Dmitri.`
- 1: `Ride` / `Pick me up near 8100 Lee Hwy, my name is Dmitri.`
- 2: `Ride` / `Pick me up near 8100 Lee Hwy, my name is [NAME].`
- 4: `Ride` / `Pick me up near [ADDRESS], my name is [NAME].`
- 5: `Ride` / `Pick me up near [ADDRESS], my name is [NAME].`

</details>

<details><summary>P44</summary>

- original: `Meals` / `Contact my caseworker Ana Souza: ana.souza@example.org`
- 1: `Meals` / `Contact my caseworker Ana Souza: [EMAIL]`
- 2: `Meals` / `Contact my caseworker Ana Souza: [EMAIL]`
- 4: `Meals` / `Contact my caseworker [NAME]: [EMAIL]`
- 5: `Meals` / `Contact my caseworker Ana Souza: [EMAIL]`

</details>

<details><summary>P45</summary>

- original: `Help please` / `Call me at 1-800-555-0100 or my cell 571 5550123.`
- 1: `Help please` / `Call me at [PHONE] or my cell [PHONE].`
- 2: `Help please` / `Call me at [PHONE] or my cell [PHONE].`
- 4: `Help please` / `Call me at [PHONE] or my cell [PHONE].`
- 5: `Help please` / `Call me at [PHONE] or my cell [PHONE].`

</details>

<details><summary>P46</summary>

- original: `Tutor` / `I'm Nguyen, student at the community college, need maths help.`
- 1: `Tutor` / `I'm Nguyen, student at the community college, need maths help.`
- 2: `Tutor` / `I'm [NAME], student at the community college, need maths help.`
- 4: `Tutor` / `I'm [NAME], student at the community college, need maths help.`
- 5: `Tutor` / `I'm [NAME], student at the community college, need maths help.`

</details>

<details><summary>P47</summary>

- original: `Hospital visit` / `My wife Fatima is in the hospital, need someone to cook. My email is f_alsayed_99@example.com`
- 1: `Hospital visit` / `My wife Fatima is in the hospital, need someone to cook. My email is [EMAIL]`
- 2: `Hospital visit` / `My wife [NAME] is in the hospital, need someone to cook. My email is [EMAIL]`
- 4: `Hospital visit` / `My wife [NAME] is in the hospital, need someone to cook. My email is [EMAIL]`
- 5: `Hospital visit` / `My wife [NAME] is in the hospital, need someone to cook. My email is [EMAIL]`

</details>

<details><summary>P48</summary>

- original: `Phone repair` / `My number: (571)555-0134. Name: O. Adeyemi`
- 1: `Phone repair` / `My number: [PHONE]. Name: O. Adeyemi`
- 2: `Phone repair` / `My number: [PHONE]. Name: O. [NAME]`
- 4: `Phone repair` / `My number: [PHONE]. Name: [NAME]`
- 5: `Phone repair` / `My number: [PHONE]. Name: [NAME]`

</details>

<details><summary>P49</summary>

- original: `Groceries` / `Deliver to Flat 12, 4 Park Road, Mumbai 400050. Contact Rajesh Kumar.`
- 1: `Groceries` / `Deliver to Flat 12, 4 Park Road, Mumbai 400050. Contact Rajesh Kumar.`
- 2: `Groceries` / `Deliver to Flat 12, 4 Park Road, Mumbai 400050. Contact Rajesh [NAME].`
- 4: `Groceries` / `Deliver to [ADDRESS], Mumbai 400050. Contact [NAME].`
- 5: `Groceries` / `Deliver to [ADDRESS], Mumbai 400050. Contact [NAME].`

</details>

<details><summary>P50</summary>

- original: `Clothes donation pickup` / `Please email me at wei.zhang [at] example [dot] com to arrange pickup.`
- 1: `Clothes donation pickup` / `Please email me at wei.zhang [at] example [dot] com to arrange pickup.`
- 2: `Clothes donation pickup` / `Please email me at [NAME].[NAME] [at] example [dot] com to arrange pickup.`
- 4: `Clothes donation pickup` / `Please email me at [EMAIL] to arrange pickup.`
- 5: `Clothes donation pickup` / `Please email me at [EMAIL] to arrange pickup.`

</details>

<details><summary>C01</summary>

- original: `Need groceries` / `We need rice, beans and cooking oil for a family of five.`
- 1: `Need groceries` / `We need rice, beans and cooking oil for a family of five.`
- 2: `Need groceries` / `We need rice, beans and cooking oil for a family of five.`
- 4: `Need groceries` / `We need rice, beans and cooking oil for a family of five.`
- 5: `Need groceries` / `We need rice, beans and cooking oil for a family of five.`

</details>

<details><summary>C02</summary>

- original: `Ride to the food bank` / `The Main Street food bank opens at 9am on Saturdays; I need a ride there.`
- 1: `Ride to the food bank` / `The Main Street food bank opens at 9am on Saturdays; I need a ride there.`
- 2: `Ride to the food bank` / `The Main Street food bank opens at 9am on Saturdays; I need a ride there.`
- 4: `Ride to the food bank` / `The Main Street food bank opens at 9am on Saturdays; I need a ride there.`
- 5: `Ride to the food bank` / `The Main Street food bank opens at 9am on Saturdays; I need a ride there.`

</details>

<details><summary>C03</summary>

- original: `Help with homework` / `My kids need help with grade 7 math and reading, two evenings a week.`
- 1: `Help with homework` / `My kids need help with grade 7 math and reading, two evenings a week.`
- 2: `Help with homework` / `My kids need help with grade 7 math and reading, two evenings a week.`
- 4: `Help with homework` / `My kids need help with grade 7 math and reading, two evenings a week.`
- 5: `Help with homework` / `My kids need help with grade 7 math and reading, two evenings a week.`

</details>

<details><summary>C04</summary>

- original: `Grace period on rent` / `I hope the landlord will give me a grace period. Can someone help me write a letter?`
- 1: `Grace period on rent` / `I hope the landlord will give me a grace period. Can someone help me write a letter?`
- 2: `[NAME] period on rent` / `I [NAME] the landlord will give me a [NAME] period. Can someone help me write a letter?`
- 4: `Grace period on rent` / `I hope the landlord will give me a grace period. Can someone help me write a letter?`
- 5: `Grace period on rent` / `I hope the landlord will give me a grace period. Can someone help me write a letter?`

</details>

<details><summary>C05</summary>

- original: `Winter coats` / `Looking for 3 winter coats, sizes 8, 10 and 12.`
- 1: `Winter coats` / `Looking for 3 winter coats, sizes 8, 10 and 12.`
- 2: `Winter coats` / `Looking for 3 winter coats, sizes 8, 10 and 12.`
- 4: `Winter coats` / `Looking for 3 winter coats, sizes 8, 10 and 12.`
- 5: `Winter coats` / `Looking for 3 winter coats, sizes 8, 10 and 12.`

</details>

<details><summary>C06</summary>

- original: `Medicine` / `I may need help picking up medicine from the CVS pharmacy every month.`
- 1: `Medicine` / `I may need help picking up medicine from the CVS pharmacy every month.`
- 2: `Medicine` / `I [NAME] need help picking up medicine from the CVS pharmacy every month.`
- 4: `Medicine` / `I may need help picking up medicine from the CVS pharmacy every month.`
- 5: `Medicine` / `I may need help picking up medicine from the CVS pharmacy every month.`

</details>

<details><summary>C07</summary>

- original: `Furniture` / `We need a bed and 2 chairs after moving into a new apartment in May.`
- 1: `Furniture` / `We need a bed and 2 chairs after moving into a new apartment in May.`
- 2: `Furniture` / `We need a bed and 2 chairs after moving into a new apartment in [NAME].`
- 4: `Furniture` / `We need a bed and 2 chairs after moving into a new apartment in May.`
- 5: `Furniture` / `We need a bed and 2 chairs after moving into a new apartment in May.`

</details>

<details><summary>C08</summary>

- original: `Transport` / `Need transport to Inova Fairfax Hospital for a 10:30 appointment on 11/20.`
- 1: `Transport` / `Need transport to Inova Fairfax Hospital for a 10:30 appointment on 11/20.`
- 2: `Transport` / `Need transport to Inova Fairfax Hospital for a 10:30 appointment on 11/20.`
- 4: `Transport` / `Need transport to Inova Fairfax Hospital for a 10:30 appointment on 11/20.`
- 5: `Transport` / `Need transport to Inova Fairfax Hospital for a 10:30 appointment on 11/20.`

</details>

<details><summary>C09</summary>

- original: `Food` / `Order #45821 from the pantry never arrived, please help.`
- 1: `Food` / `Order #45821 from the pantry never arrived, please help.`
- 2: `Food` / `Order #45821 from the pantry never arrived, please help.`
- 4: `Food` / `Order #45821 from the pantry never arrived, please help.`
- 5: `Food` / `Order #45821 from the pantry never arrived, please help.`

</details>

<details><summary>C10</summary>

- original: `Job search` / `Looking for help writing a cover letter for a warehouse job paying $18.50/hour.`
- 1: `Job search` / `Looking for help writing a cover letter for a warehouse job paying $18.50/hour.`
- 2: `Job search` / `Looking for help writing a cover letter for a warehouse job paying $18.50/hour.`
- 4: `Job search` / `Looking for help writing a cover letter for a warehouse job paying $18.50/hour.`
- 5: `Job search` / `Looking for help writing a cover letter for a warehouse job paying $18.50/hour.`

</details>

<details><summary>C11</summary>

- original: `Tutoring` / `Need an English tutor; I speak Spanish and Hindi at home.`
- 1: `Tutoring` / `Need an English tutor; I speak Spanish and Hindi at home.`
- 2: `Tutoring` / `Need an English tutor; I speak Spanish and Hindi at home.`
- 4: `Tutoring` / `Need an English tutor; I speak Spanish and Hindi at home.`
- 5: `Tutoring` / `Need an English tutor; I speak Spanish and Hindi at home.`

</details>

<details><summary>C12</summary>

- original: `Utilities` / `Our electricity bill is 3 months overdue, around 450 dollars.`
- 1: `Utilities` / `Our electricity bill is 3 months overdue, around 450 dollars.`
- 2: `Utilities` / `Our electricity bill is 3 months overdue, around 450 dollars.`
- 4: `Utilities` / `Our electricity bill is 3 months overdue, around 450 dollars.`
- 5: `Utilities` / `Our electricity bill is 3 months overdue, around 450 dollars.`

</details>

<details><summary>C13</summary>

- original: `Help with taxes` / `Need help with Form 1040 and the 2025 child tax credit.`
- 1: `Help with taxes` / `Need help with Form 1040 and the 2025 child tax credit.`
- 2: `Help with taxes` / `Need help with Form 1040 and the 2025 child tax credit.`
- 4: `Help with taxes` / `Need help with Form 1040 and the 2025 child tax credit.`
- 5: `Help with taxes` / `Need help with Form 1040 and the 2025 child tax credit.`

</details>

<details><summary>C14</summary>

- original: `Elder care` / `My grandmother needs someone to check on her twice a week.`
- 1: `Elder care` / `My grandmother needs someone to check on her twice a week.`
- 2: `Elder care` / `My grandmother needs someone to check on her twice a week.`
- 4: `Elder care` / `My grandmother needs someone to check on her twice a week.`
- 5: `Elder care` / `My grandmother needs someone to check on her twice a week.`

</details>

<details><summary>C15</summary>

- original: `Donation` / `Donate 25 cans of soup to the Red Cross shelter on Route 7.`
- 1: `Donation` / `Donate 25 cans of soup to the Red Cross shelter on Route 7.`
- 2: `Donation` / `Donate 25 cans of soup to the Red Cross shelter on Route 7.`
- 4: `Donation` / `Donate 25 cans of soup to the Red Cross shelter on Route 7.`
- 5: `Donation` / `Donate 25 cans of soup to the Red Cross shelter on Route 7.`

</details>

<details><summary>C16</summary>

- original: `Wheelchair` / `Need a wheelchair for 6 to 8 weeks after knee surgery.`
- 1: `Wheelchair` / `Need a wheelchair for 6 to 8 weeks after knee surgery.`
- 2: `Wheelchair` / `Need a wheelchair for 6 to 8 weeks after knee surgery.`
- 4: `Wheelchair` / `Need a wheelchair for 6 to 8 weeks after knee surgery.`
- 5: `Wheelchair` / `Need a wheelchair for 6 to 8 weeks after knee surgery.`

</details>

<details><summary>C17</summary>

- original: `Prescription` / `Insulin supply runs out on December 3rd; need help applying for assistance.`
- 1: `Prescription` / `Insulin supply runs out on December 3rd; need help applying for assistance.`
- 2: `Prescription` / `Insulin supply runs out on December 3rd; need help applying for assistance.`
- 4: `Prescription` / `Insulin supply runs out on December 3rd; need help applying for assistance.`
- 5: `Prescription` / `Insulin supply runs out on December 3rd; need help applying for assistance.`

</details>

<details><summary>C18</summary>

- original: `Car repair` / `My 2012 Honda Civic needs new brakes, the quote was 300-400 dollars.`
- 1: `Car repair` / `My 2012 Honda Civic needs new brakes, the quote was 300-400 dollars.`
- 2: `Car repair` / `My 2012 Honda Civic needs new brakes, the quote was 300-400 dollars.`
- 4: `Car repair` / `My 2012 Honda Civic needs new brakes, the quote was 300-400 dollars.`
- 5: `Car repair` / `My 2012 Honda Civic needs new brakes, the quote was 300-400 dollars.`

</details>

<details><summary>C19</summary>

- original: `Counseling` / `Looking for free counseling services near Washington DC.`
- 1: `Counseling` / `Looking for free counseling services near Washington DC.`
- 2: `Counseling` / `Looking for free counseling services near Washington DC.`
- 4: `Counseling` / `Looking for free counseling services near Washington DC.`
- 5: `Counseling` / `Looking for free counseling services near Washington DC.`

</details>

<details><summary>C20</summary>

- original: `Shelter` / `Family of 4 needs emergency shelter for 2 nights, call the 211 hotline for details.`
- 1: `Shelter` / `Family of 4 needs emergency shelter for 2 nights, call the 211 hotline for details.`
- 2: `Shelter` / `Family of 4 needs emergency shelter for 2 nights, call the 211 hotline for details.`
- 4: `Shelter` / `Family of 4 needs emergency shelter for 2 nights, call the 211 hotline for details.`
- 5: `Shelter` / `Family of 4 needs emergency shelter for 2 nights, call the 211 hotline for details.`

</details>

<details><summary>C21</summary>

- original: `County paperwork` / `Reference number 2026 1104 5567 89 from the county office, need help reading the letter.`
- 1: `County paperwork` / `Reference number [CARD]from the county office, need help reading the letter.`
- 2: `County paperwork` / `Reference number [CARD]from the county office, need help reading the letter.`
- 4: `County paperwork` / `Reference number 2026 1104 5567 89 from the county office, need help reading the letter.`
- 5: `County paperwork` / `Reference number 2026 1104 5567 89 from the county office, need help reading the letter.`

</details>

<details><summary>C22</summary>

- original: `Food drive` / `Can volunteers help with the Martin Luther King Jr. Day food drive at the school?`
- 1: `Food drive` / `Can volunteers help with the Martin Luther King Jr. Day food drive at the school?`
- 2: `Food drive` / `Can volunteers help with the Martin Luther King Jr. Day food drive at the school?`
- 4: `Food drive` / `Can volunteers help with the Martin Luther King Jr. Day food drive at the school?`
- 5: `Food drive` / `Can volunteers help with the [NAME] food drive at the school?`

</details>

