Test set: 24 requests, 16 with personal details, 8 without. 19 labelled details.

| Approach | Caught | Partly caught | Missed | PII texts fully cleaned | Clean texts wrongly redacted | False-positive redactions | Time per request |
|---|---|---|---|---|---|---|---|
| 1. Pattern matching only (current pipeline) | 5 (26%) | 0 | 14 | 2 / 16 | 0 / 8 | 0 | 0.014 ms |
| 2. Patterns + users-table name lookup | 6 (32%) | 0 | 13 | 3 / 16 | 0 / 8 | 0 | 0.025 ms |
| 3. Patterns + Amazon Comprehend | not run: no AWS access yet (run with --comprehend live) | | | | | | |
| 4. Improved patterns + users names + name cues | 13 (68%) | 2 | 4 | 10 / 16 | 0 / 8 | 0 | 0.108 ms |

Caught per type (caught / total):

| Approach | NAME | PHONE | EMAIL | ADDRESS | ID | CARD | URL | Names of users | Names of non-users |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0/9 | 4/6 | 1/2 | 0/2 | 0/0 | 0/0 | 0/0 | 0/2 | 0/7 |
| 2 | 1/9 | 4/6 | 1/2 | 0/2 | 0/0 | 0/0 | 0/0 | 1/2 | 0/7 |
| 4 | 6/9 | 5/6 | 2/2 | 0/2 | 0/0 | 0/0 | 0/0 | 1/2 | 5/7 |

Clean texts wrongly redacted:

- **1**: none
- **2**: none
- **4**: none

Comprehend cost: average request 74.4 characters = 3.0 units (minimum 3) = $0.00030 per request. 1,000 requests/month = $0.3, 10,000 requests/month = $3.0, 100,000 requests/month = $30.0.

Name lookup: 386 name parts, built in 20.64 ms.

## Redacted output per request

<details><summary>H01</summary>

- **1** `Need diapers` / `Spoke with Aleksandra Nowak at the shelter, she said to ask here. Size 4 diapers please.`  
  not caught: Aleksandra Nowak (missed)
- **2** `Need diapers` / `Spoke with Aleksandra Nowak at the shelter, she said to ask here. Size 4 diapers please.`  
  not caught: Aleksandra Nowak (missed)
- **4** `Need diapers` / `Spoke with [NAME] at the shelter, she said to ask here. Size 4 diapers please.`

</details>

<details><summary>H02</summary>

- **1** `Signed up for meals` / `We need meals for two weeks after the baby arrives. Signed: Tomás Ortega`  
  not caught: Tomás Ortega (missed)
- **2** `Signed up for meals` / `We need meals for two weeks after the baby arrives. Signed: Tomás Ortega`  
  not caught: Tomás Ortega (missed)
- **4** `Signed up for meals` / `We need meals for two weeks after the baby arrives. Signed: Tomás Ortega`  
  not caught: Tomás Ortega (missed)

</details>

<details><summary>H03</summary>

- **1** `Contact person` / `Contact person - Nadia Haddad, best reached in the evening.`  
  not caught: Nadia Haddad (missed)
- **2** `Contact person` / `Contact person - Nadia Haddad, best reached in the evening.`  
  not caught: Nadia Haddad (missed)
- **4** `Contact person` / `Contact person - Nadia Haddad, best reached in the evening.`  
  not caught: Nadia Haddad (missed)

</details>

<details><summary>H04</summary>

- **1** `PLEASE HELP` / `PLEASE CALL SUNIL AT [PHONE] (CELL). NEED FOOD URGENTLY.`  
  not caught: SUNIL (missed)
- **2** `PLEASE HELP` / `PLEASE CALL SUNIL AT [PHONE] (CELL). NEED FOOD URGENTLY.`  
  not caught: SUNIL (missed)
- **4** `PLEASE HELP` / `PLEASE CALL [NAME] [PHONE] (CELL). NEED FOOD URGENTLY.`

</details>

<details><summary>H05</summary>

- **1** `Help for my uncle` / `My uncle Bao is 80 and needs someone to help him with his medicines.`  
  not caught: Bao (missed)
- **2** `Help for my uncle` / `My uncle Bao is 80 and needs someone to help him with his medicines.`  
  not caught: Bao (missed)
- **4** `Help for my uncle` / `My uncle [NAME] is 80 and needs someone to help him with his medicines.`

</details>

<details><summary>H06</summary>

- **1** `Ride needed` / `Ride needed from Lakshmi's house to the temple on Sunday morning.`  
  not caught: Lakshmi (missed)
- **2** `Ride needed` / `Ride needed from Lakshmi's house to the temple on Sunday morning.`  
  not caught: Lakshmi (missed)
- **4** `Ride needed` / `Ride needed from Lakshmi's house to the temple on Sunday morning.`  
  not caught: Lakshmi (missed)

</details>

<details><summary>H07</summary>

- **1** `Phone number` / `phone: 408‑555‑0133 (please leave a voicemail)`  
  not caught: 408‑555‑0133 (missed)
- **2** `Phone number` / `phone: 408‑555‑0133 (please leave a voicemail)`  
  not caught: 408‑555‑0133 (missed)
- **4** `Phone number` / `phone: 408‑555‑0133 (please leave a voicemail)`  
  not caught: 408‑555‑0133 (missed)

</details>

<details><summary>H08</summary>

- **1** `Moving help` / `Moving out of my place on the weekend, my cell is [PHONE].`
- **2** `Moving help` / `Moving out of my place on the weekend, my cell is [PHONE].`
- **4** `Moving help` / `Moving out of my place on the weekend, my cell is [PHONE].`

</details>

<details><summary>H09</summary>

- **1** `Family in Mexico` / `My sister in Mexico City needs medicine sent. Her WhatsApp is +52 55 1234 5678.`  
  not caught: +52 55 1234 5678 (missed)
- **2** `Family in Mexico` / `My sister in Mexico City needs medicine sent. Her WhatsApp is +52 55 1234 5678.`  
  not caught: +52 55 1234 5678 (missed)
- **4** `Family in Mexico` / `My sister in Mexico City needs medicine sent. Her WhatsApp is [PHONE].`

</details>

<details><summary>H10</summary>

- **1** `Email` / `Questions? Write to [EMAIL]`
- **2** `Email` / `Questions? Write to [EMAIL]`
- **4** `Email` / `Questions? Write to [EMAIL]`

</details>

<details><summary>H11</summary>

- **1** `Groceries` / `Deliver to Unit 5, 210 W Santa Clara St please.`  
  not caught: Unit 5, 210 W Santa Clara St (missed)
- **2** `Groceries` / `Deliver to Unit 5, 210 W Santa Clara St please.`  
  not caught: Unit 5, 210 W Santa Clara St (missed)
- **4** `Groceries` / `Deliver to Unit 5, [ADDRESS] please.`  
  not caught: Unit 5, 210 W Santa Clara St (partial)

</details>

<details><summary>H12</summary>

- **1** `Fix fence` / `Fence broke at apt 3, 45 river rd. Need a handyman.`  
  not caught: apt 3, 45 river rd (missed)
- **2** `Fix fence` / `Fence broke at apt 3, 45 river rd. Need a handyman.`  
  not caught: apt 3, 45 river rd (missed)
- **4** `Fix fence` / `Fence broke at apt 3, [ADDRESS] Need a handyman.`  
  not caught: apt 3, 45 river rd (partial)

</details>

<details><summary>H13</summary>

- **1** `Dog walking` / `Dog walker needed for Mrs. Kowalczyk while she recovers from surgery.`  
  not caught: Kowalczyk (missed)
- **2** `Dog walking` / `Dog walker needed for Mrs. Kowalczyk while she recovers from surgery.`  
  not caught: Kowalczyk (missed)
- **4** `Dog walking` / `Dog walker needed for Mrs. [NAME] while she recovers from surgery.`

</details>

<details><summary>H14</summary>

- **1** `Lunch for seniors` / `Volunteer coordinator is Wei, number [PHONE], she will share the list.`  
  not caught: Wei (missed)
- **2** `Lunch for seniors` / `Volunteer coordinator is [NAME], number [PHONE], she will share the list.`
- **4** `Lunch for seniors` / `Volunteer coordinator is [NAME], number [PHONE], she will share the list.`

</details>

<details><summary>H15</summary>

- **1** `School form` / `Need help with a school form for my kid, my email is lan.nguyen.92 at yahoo dot com`  
  not caught: lan.nguyen.92 at yahoo dot com (missed)
- **2** `School form` / `Need help with a school form for my kid, my email is lan.nguyen.92 at yahoo dot com`  
  not caught: lan.nguyen.92 at yahoo dot com (missed)
- **4** `School form` / `Need help with a school form for my kid, my email is [NAME]`

</details>

<details><summary>H16</summary>

- **1** `Car seat` / `Need a car seat. I'm Precious Moyo, you can reach me on [PHONE].`  
  not caught: Precious Moyo (missed)
- **2** `Car seat` / `Need a car seat. I'm Precious Moyo, you can reach me on [PHONE].`  
  not caught: Precious Moyo (missed)
- **4** `Car seat` / `Need a car seat. I'm [NAME], you can reach me on [PHONE].`

</details>

<details><summary>HC1</summary>

- **1** `Park cleanup` / `Volunteers needed for the Will Rogers Park cleanup on Saturday.`
- **2** `Park cleanup` / `Volunteers needed for the Will Rogers Park cleanup on Saturday.`
- **4** `Park cleanup` / `Volunteers needed for the Will Rogers Park cleanup on Saturday.`

</details>

<details><summary>HC2</summary>

- **1** `Rent went up` / `Rent increased from 1800 to 2100 and I cannot cover the gap.`
- **2** `Rent went up` / `Rent increased from 1800 to 2100 and I cannot cover the gap.`
- **4** `Rent went up` / `Rent increased from 1800 to 2100 and I cannot cover the gap.`

</details>

<details><summary>HC3</summary>

- **1** `Info line` / `I called 211 but they told me to post here.`
- **2** `Info line` / `I called 211 but they told me to post here.`
- **4** `Info line` / `I called 211 but they told me to post here.`

</details>

<details><summary>HC4</summary>

- **1** `Coat drive` / `Is the Salvation Army coat drive still open this week?`
- **2** `Coat drive` / `Is the Salvation Army coat drive still open this week?`
- **4** `Coat drive` / `Is the Salvation Army coat drive still open this week?`

</details>

<details><summary>HC5</summary>

- **1** `Kids shoes` / `Need shoes for my two kids, sizes 13 and 2.`
- **2** `Kids shoes` / `Need shoes for my two kids, sizes 13 and 2.`
- **4** `Kids shoes` / `Need shoes for my two kids, sizes 13 and 2.`

</details>

<details><summary>HC6</summary>

- **1** `Interview clothes` / `I have a job interview at Target on Monday and need a shirt.`
- **2** `Interview clothes` / `I have a job interview at Target on Monday and need a shirt.`
- **4** `Interview clothes` / `I have a job interview at Target on Monday and need a shirt.`

</details>

<details><summary>HC7</summary>

- **1** `Faith based help` / `Looking for a church or mosque food pantry near Santa Clara.`
- **2** `Faith based help` / `Looking for a church or mosque food pantry near Santa Clara.`
- **4** `Faith based help` / `Looking for a church or mosque food pantry near Santa Clara.`

</details>

<details><summary>HC8</summary>

- **1** `Bills` / `My PG&E bill of $310 is overdue, account is in my name.`
- **2** `Bills` / `My PG&E bill of $310 is overdue, account is in my name.`
- **4** `Bills` / `My PG&E bill of $310 is overdue, account is in my name.`

</details>

