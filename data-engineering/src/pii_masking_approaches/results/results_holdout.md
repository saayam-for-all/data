# Results: PII masking approaches (#585), holdout set

Test set: 30 requests (20 with personal details, 10 without), 26 labelled details. Users-table names: 408 name parts, loaded in 8.8 ms.

| Approach | Caught | Partly | Missed | PII requests fully cleaned | Clean requests wrongly redacted | False-positive redactions | Time per request |
|---|---|---|---|---|---|---|---|
| 1. Pipeline patterns only | 5 (19.2%) | 0 | 21 | 2/20 | 0/10 | 0 | 0.0049 ms |
| 2. Pipeline + users-table lookup | 8 (30.8%) | 1 | 17 | 4/20 | 0/10 | 0 | 0.0093 ms |
| 3. Pipeline + Amazon Comprehend | not run: no AWS access yet (run with --comprehend) | | | | | | |
| 4. Improved rules (patterns + users names + name cues) | 20 (76.9%) | 1 | 5 | 14/20 | 0/10 | 0 | 0.0446 ms |
| 5. Improved patterns + spaCy small model (reference) | 24 (92.3%) | 0 | 2 | 18/20 | 0/10 | 3 | 4.0884 ms |

## Caught per type

| Approach | NAME | PHONE | EMAIL | ADDRESS | ID | CARD | URL | DOB |
|---|---|---|---|---|---|---|---|---|
| 1. Pipeline patterns only | 0/14 | 3/6 | 2/2 | 0/3 | 0/1 | - | - | - |
| 2. Pipeline + users-table lookup | 3/14 | 3/6 | 2/2 | 0/3 | 0/1 | - | - | - |
| 4. Improved rules (patterns + users names + name cues) | 8/14 | 6/6 | 2/2 | 3/3 | 1/1 | - | - | - |
| 5. Improved patterns + spaCy small model (reference) | 12/14 | 6/6 | 2/2 | 3/3 | 1/1 | - | - | - |

## Not fully caught

- **1. Pipeline patterns only**: H02 NAME (missed), H03 NAME (missed), H03 ADDRESS (missed), H05 PHONE (missed), H06 NAME (missed), H07 ADDRESS (missed), H08 NAME (missed), H09 NAME (missed), H10 NAME (missed), H11 PHONE (missed), H12 NAME (missed), H13 ID (missed), H14 NAME (missed), H15 ADDRESS (missed), H15 NAME (missed), H16 NAME (missed), H16 NAME (missed), H17 NAME (missed), H18 PHONE (missed), H19 NAME (missed), H20 NAME (missed)
- **2. Pipeline + users-table lookup**: H02 NAME (missed), H03 NAME (missed), H03 ADDRESS (missed), H05 PHONE (missed), H06 NAME (missed), H07 ADDRESS (missed), H09 NAME (missed), H10 NAME (missed), H11 PHONE (missed), H12 NAME (missed), H13 ID (missed), H15 ADDRESS (missed), H15 NAME (missed), H16 NAME (partly), H17 NAME (missed), H18 PHONE (missed), H19 NAME (missed), H20 NAME (missed)
- **4. Improved rules (patterns + users names + name cues)**: H02 NAME (missed), H03 NAME (missed), H06 NAME (missed), H15 NAME (missed), H16 NAME (partly), H19 NAME (missed)
- **5. Improved patterns + spaCy small model (reference)**: H10 NAME (missed), H15 NAME (missed)

## Clean requests wrongly redacted

- **1. Pipeline patterns only**: none
- **2. Pipeline + users-table lookup**: none
- **4. Improved rules (patterns + users names + name cues)**: none
- **5. Improved patterns + spaCy small model (reference)**: none

## Masked output per request

<details><summary>H01</summary>

- original: `Groceries` / `pls call my mobile 240 555 0187 thx`
- 1: `Groceries` / `pls call my mobile [PHONE] thx`
- 2: `Groceries` / `pls call my mobile [PHONE] thx`
- 4: `Groceries` / `pls call my mobile [PHONE] thx`
- 5: `Groceries` / `pls call my mobile [PHONE] thx`

</details>

<details><summary>H02</summary>

- original: `Help w/ kids` / `I'm a single dad, Carlos Mendoza, two kids under 5.`
- 1: `Help w/ kids` / `I'm a single dad, Carlos Mendoza, two kids under 5.`
- 2: `Help w/ kids` / `I'm a single dad, Carlos Mendoza, two kids under 5.`
- 4: `Help w/ kids` / `I'm a single dad, Carlos Mendoza, two kids under 5.`
- 5: `Help w/ kids` / `I'm a single dad, [NAME], two kids under 5.`

</details>

<details><summary>H03</summary>

- original: `Ride to dialysis` / `Mrs Okonkwo needs a ride Mon/Wed/Fri, she is at 4512 Willow Creek Rd.`
- 1: `Ride to dialysis` / `Mrs Okonkwo needs a ride Mon/Wed/Fri, she is at 4512 Willow Creek Rd.`
- 2: `Ride to dialysis` / `Mrs Okonkwo needs a ride Mon/Wed/Fri, she is at 4512 Willow Creek Rd.`
- 4: `Ride to dialysis` / `Mrs Okonkwo needs a ride Mon/Wed/Fri, she is at [ADDRESS].`
- 5: `Ride to dialysis` / `[NAME] needs a ride Mon/Wed/Fri, she is at [ADDRESS].`

</details>

<details><summary>H04</summary>

- original: `Food` / `you can email me anytime: sunita.sharma1975@yahoo.co.in`
- 1: `Food` / `you can email me anytime: [EMAIL]`
- 2: `Food` / `you can email me anytime: [EMAIL]`
- 4: `Food` / `you can email me anytime: [EMAIL]`
- 5: `Food` / `you can email me anytime: [EMAIL]`

</details>

<details><summary>H05</summary>

- original: `Phone` / `My contact is +971 50 123 4567 (UAE).`
- 1: `Phone` / `My contact is +971 50 123 4567 (UAE).`
- 2: `Phone` / `My contact is +971 50 123 4567 (UAE).`
- 4: `Phone` / `My contact is [PHONE] (UAE).`
- 5: `Phone` / `My contact is [PHONE] (UAE).`

</details>

<details><summary>H06</summary>

- original: `Need help` / `My daughter is Mei Ling and she needs school uniforms.`
- 1: `Need help` / `My daughter is Mei Ling and she needs school uniforms.`
- 2: `Need help` / `My daughter is Mei Ling and she needs school uniforms.`
- 4: `Need help` / `My daughter is Mei Ling and she needs school uniforms.`
- 5: `Need help` / `My daughter is [NAME] and she needs school uniforms.`

</details>

<details><summary>H07</summary>

- original: `Moving` / `New address is Apt 7, 22 Cedar Blvd, Ashburn VA.`
- 1: `Moving` / `New address is Apt 7, 22 Cedar Blvd, Ashburn VA.`
- 2: `Moving` / `New address is Apt 7, 22 Cedar Blvd, Ashburn VA.`
- 4: `Moving` / `New address is [ADDRESS], Ashburn VA.`
- 5: `Moving` / `New address is [ADDRESS], [NAME].`

</details>

<details><summary>H08</summary>

- original: `Rent` / `Landlord is Mr. Patel, his number is 571.555.0166.`
- 1: `Rent` / `Landlord is Mr. Patel, his number is [PHONE].`
- 2: `Rent` / `Landlord is Mr. [NAME], his number is [PHONE].`
- 4: `Rent` / `Landlord is Mr. [NAME], his number is [PHONE].`
- 5: `Rent` / `[NAME] is Mr. [NAME], his number is [PHONE].`

</details>

<details><summary>H09</summary>

- original: `Medicine` / `Ask for Hiroshi at the pharmacy counter.`
- 1: `Medicine` / `Ask for Hiroshi at the pharmacy counter.`
- 2: `Medicine` / `Ask for Hiroshi at the pharmacy counter.`
- 4: `Medicine` / `Ask for [NAME] at the pharmacy counter.`
- 5: `Medicine` / `Ask for [NAME] at the pharmacy counter.`

</details>

<details><summary>H10</summary>

- original: `Food` / `Me llamo Ana María López y necesito comida para mis hijos.`
- 1: `Food` / `Me llamo Ana María López y necesito comida para mis hijos.`
- 2: `Food` / `Me llamo Ana María López y necesito comida para mis hijos.`
- 4: `Food` / `Me llamo [NAME] y necesito comida para mis hijos.`
- 5: `Food` / `Me llamo Ana María López y necesito comida para mis [NAME].`

</details>

<details><summary>H11</summary>

- original: `Ride` / `call me on two zero two, five five five, zero one four four`
- 1: `Ride` / `call me on two zero two, five five five, zero one four four`
- 2: `Ride` / `call me on two zero two, five five five, zero one four four`
- 4: `Ride` / `call me on [PHONE]`
- 5: `Ride` / `call me on [PHONE]`

</details>

<details><summary>H12</summary>

- original: `Tutoring` / `Kindly contact Ms. Adaeze Nwosu, my sister, regarding tutoring.`
- 1: `Tutoring` / `Kindly contact Ms. Adaeze Nwosu, my sister, regarding tutoring.`
- 2: `Tutoring` / `Kindly contact Ms. Adaeze Nwosu, my sister, regarding tutoring.`
- 4: `Tutoring` / `Kindly contact Ms. [NAME], my sister, regarding tutoring.`
- 5: `Tutoring` / `Kindly contact Ms. [NAME], my sister, regarding tutoring.`

</details>

<details><summary>H13</summary>

- original: `Bills` / `My driver license number is D123-4567-8901.`
- 1: `Bills` / `My driver license number is D123-4567-8901.`
- 2: `Bills` / `My driver license number is D123-4567-8901.`
- 4: `Bills` / `My driver license number is [ID].`
- 5: `Bills` / `My driver license number is [ID].`

</details>

<details><summary>H14</summary>

- original: `Help` / `This is Fatima again, the phone number changed to 703 555 0102.`
- 1: `Help` / `This is Fatima again, the phone number changed to [PHONE].`
- 2: `Help` / `This is [NAME] again, the phone number changed to [PHONE].`
- 4: `Help` / `This is [NAME] again, the phone number changed to [PHONE].`
- 5: `Help` / `This is [NAME] again, the phone number changed to [PHONE].`

</details>

<details><summary>H15</summary>

- original: `Groceries` / `Deliver to 1600 Pennsylvania Avenue NW please, ring twice. -Tom`
- 1: `Groceries` / `Deliver to 1600 Pennsylvania Avenue NW please, ring twice. -Tom`
- 2: `Groceries` / `Deliver to 1600 Pennsylvania Avenue NW please, ring twice. -Tom`
- 4: `Groceries` / `Deliver to [ADDRESS] NW please, ring twice. -Tom`
- 5: `Groceries` / `Deliver to [ADDRESS] NW please, ring twice. -Tom`

</details>

<details><summary>H16</summary>

- original: `School form` / `Child: Arjun Reddy, age 9. Parent: Kavya Reddy.`
- 1: `School form` / `Child: Arjun Reddy, age 9. Parent: Kavya Reddy.`
- 2: `School form` / `Child: [NAME] [NAME], age 9. Parent: Kavya [NAME].`
- 4: `School form` / `Child: [NAME], age 9. Parent: Kavya [NAME].`
- 5: `School form` / `Child: [NAME], age 9. Parent: [NAME].`

</details>

<details><summary>H17</summary>

- original: `Visit` / `Please visit my grandpa Giuseppe Rossi, he lives alone.`
- 1: `Visit` / `Please visit my grandpa Giuseppe Rossi, he lives alone.`
- 2: `Visit` / `Please visit my grandpa Giuseppe Rossi, he lives alone.`
- 4: `Visit` / `Please visit my grandpa [NAME], he lives alone.`
- 5: `Visit` / `Please visit my grandpa [NAME], he lives alone.`

</details>

<details><summary>H18</summary>

- original: `Phone` / `WhatsApp only: 0300-1234567`
- 1: `Phone` / `WhatsApp only: 0300-1234567`
- 2: `Phone` / `WhatsApp only: 0300-1234567`
- 4: `Phone` / `WhatsApp only: [PHONE]`
- 5: `Phone` / `WhatsApp only: [PHONE]`

</details>

<details><summary>H19</summary>

- original: `Need diapers` / `Diapers size 4 for baby Noah, contact noah.mom@example.com`
- 1: `Need diapers` / `Diapers size 4 for baby Noah, contact [EMAIL]`
- 2: `Need diapers` / `Diapers size 4 for baby Noah, contact [EMAIL]`
- 4: `Need diapers` / `Diapers size 4 for baby Noah, contact [EMAIL]`
- 5: `Need diapers` / `Diapers size 4 for baby [NAME], contact [EMAIL]`

</details>

<details><summary>H20</summary>

- original: `Shelter` / `I'm Olga Petrova, I sleep in my car near the Walmart on Route 28.`
- 1: `Shelter` / `I'm Olga Petrova, I sleep in my car near the Walmart on Route 28.`
- 2: `Shelter` / `I'm Olga Petrova, I sleep in my car near the Walmart on Route 28.`
- 4: `Shelter` / `I'm [NAME], I sleep in my car near the Walmart on Route 28.`
- 5: `Shelter` / `I'm [NAME], I sleep in my car near the Walmart on Route 28.`

</details>

<details><summary>HC01</summary>

- original: `Food` / `Need baby formula and diapers for a 6 month old.`
- 1: `Food` / `Need baby formula and diapers for a 6 month old.`
- 2: `Food` / `Need baby formula and diapers for a 6 month old.`
- 4: `Food` / `Need baby formula and diapers for a 6 month old.`
- 5: `Food` / `Need baby formula and diapers for a 6 month old.`

</details>

<details><summary>HC02</summary>

- original: `Ride` / `Need a ride to the Social Security office on Monday at 10am.`
- 1: `Ride` / `Need a ride to the Social Security office on Monday at 10am.`
- 2: `Ride` / `Need a ride to the Social Security office on Monday at 10am.`
- 4: `Ride` / `Need a ride to the Social Security office on Monday at 10am.`
- 5: `Ride` / `Need a ride to the Social Security office on Monday at 10am.`

</details>

<details><summary>HC03</summary>

- original: `Help` / `Please call back when a volunteer is available.`
- 1: `Help` / `Please call back when a volunteer is available.`
- 2: `Help` / `Please call back when a volunteer is available.`
- 4: `Help` / `Please call back when a volunteer is available.`
- 5: `Help` / `Please call back when a volunteer is available.`

</details>

<details><summary>HC04</summary>

- original: `Rent` / `Rent of $1,450 is due on the 1st; I can pay $700.`
- 1: `Rent` / `Rent of $1,450 is due on the 1st; I can pay $700.`
- 2: `Rent` / `Rent of $1,450 is due on the 1st; I can pay $700.`
- 4: `Rent` / `Rent of $1,450 is due on the 1st; I can pay $700.`
- 5: `Rent` / `Rent of $1,450 is due on the 1st; I can pay $700.`

</details>

<details><summary>HC05</summary>

- original: `Tutoring` / `Need help preparing for the SAT in March.`
- 1: `Tutoring` / `Need help preparing for the SAT in March.`
- 2: `Tutoring` / `Need help preparing for the SAT in March.`
- 4: `Tutoring` / `Need help preparing for the SAT in March.`
- 5: `Tutoring` / `Need help preparing for the SAT in March.`

</details>

<details><summary>HC06</summary>

- original: `Clothes` / `Looking for a size 10 dress for a job interview at Target.`
- 1: `Clothes` / `Looking for a size 10 dress for a job interview at Target.`
- 2: `Clothes` / `Looking for a size 10 dress for a job interview at Target.`
- 4: `Clothes` / `Looking for a size 10 dress for a job interview at Target.`
- 5: `Clothes` / `Looking for a size 10 dress for a job interview at Target.`

</details>

<details><summary>HC07</summary>

- original: `Utilities` / `Account 00123 is overdue; can someone help negotiate a payment plan?`
- 1: `Utilities` / `Account 00123 is overdue; can someone help negotiate a payment plan?`
- 2: `Utilities` / `Account 00123 is overdue; can someone help negotiate a payment plan?`
- 4: `Utilities` / `Account 00123 is overdue; can someone help negotiate a payment plan?`
- 5: `Utilities` / `Account 00123 is overdue; can someone help negotiate a payment plan?`

</details>

<details><summary>HC08</summary>

- original: `Groceries` / `Need halal groceries, we are a family of 6 new to Virginia.`
- 1: `Groceries` / `Need halal groceries, we are a family of 6 new to Virginia.`
- 2: `Groceries` / `Need halal groceries, we are a family of 6 new to Virginia.`
- 4: `Groceries` / `Need halal groceries, we are a family of 6 new to Virginia.`
- 5: `Groceries` / `Need halal groceries, we are a family of 6 new to Virginia.`

</details>

<details><summary>HC09</summary>

- original: `Transport` / `Bus 5A stopped running near Lincoln Elementary, need rides to school.`
- 1: `Transport` / `Bus 5A stopped running near Lincoln Elementary, need rides to school.`
- 2: `Transport` / `Bus 5A stopped running near Lincoln Elementary, need rides to school.`
- 4: `Transport` / `Bus 5A stopped running near Lincoln Elementary, need rides to school.`
- 5: `Transport` / `Bus 5A stopped running near Lincoln Elementary, need rides to school.`

</details>

<details><summary>HC10</summary>

- original: `Help` / `My phone is broken so please email through the app instead.`
- 1: `Help` / `My phone is broken so please email through the app instead.`
- 2: `Help` / `My phone is broken so please email through the app instead.`
- 4: `Help` / `My phone is broken so please email through the app instead.`
- 5: `Help` / `My phone is broken so please email through the app instead.`

</details>

