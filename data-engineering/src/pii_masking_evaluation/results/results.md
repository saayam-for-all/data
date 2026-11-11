Test set: 70 requests, 50 with personal details, 20 without. 66 labelled details.

| Approach | Caught | Partly caught | Missed | PII texts fully cleaned | Clean texts wrongly redacted | False-positive redactions | Time per request |
|---|---|---|---|---|---|---|---|
| 1. Pattern matching only (current pipeline) | 16 (24%) | 0 | 50 | 10 / 50 | 2 / 20 | 2 | 0.016 ms |
| 2. Patterns + users-table name lookup | 44 (67%) | 1 | 21 | 29 / 50 | 5 / 20 | 8 | 0.028 ms |
| 3. Patterns + Amazon Comprehend | not run: no AWS access yet (run with --comprehend live) | | | | | | |
| 4. Improved patterns + users names + name cues | 65 (98%) | 0 | 1 | 49 / 50 | 3 / 20 | 6 | 0.127 ms |

Caught per type (caught / total):

| Approach | NAME | PHONE | EMAIL | ADDRESS | ID | CARD | URL | Names of users | Names of non-users |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0/35 | 9/15 | 4/6 | 0/7 | 1/1 | 1/1 | 1/1 | 0/30 | 0/5 |
| 2 | 28/35 | 9/15 | 4/6 | 0/7 | 1/1 | 1/1 | 1/1 | 28/30 | 0/5 |
| 4 | 34/35 | 15/15 | 6/6 | 7/7 | 1/1 | 1/1 | 1/1 | 29/30 | 5/5 |

Clean texts wrongly redacted:

- **1**: C09, C20
- **2**: C05, C06, C09, C10, C20
- **4**: C09, C10, C20

Comprehend cost: average request 85.5 characters = 3.0 units (minimum 3) = $0.00030 per request. 1,000 requests/month = $0.3, 10,000 requests/month = $3.0, 100,000 requests/month = $30.0.

Name lookup: 386 name parts, built in 21.1 ms.

## Redacted output per request

<details><summary>T01</summary>

- **1** `Need groceries this week` / `We ran out of food. Please call me at [PHONE] any time after 5pm.`
- **2** `Need groceries this week` / `We ran out of food. Please call me at [PHONE] any time after 5pm.`
- **4** `Need groceries this week` / `We ran out of food. Please call me at [PHONE] any time after 5pm.`

</details>

<details><summary>T02</summary>

- **1** `Ride to clinic` / `I need a ride to my appointment on Friday. My cell is [PHONE].`
- **2** `Ride to clinic` / `I need a ride to my appointment on Friday. My cell is [PHONE].`
- **4** `Ride to clinic` / `I need a ride to my appointment on Friday. My cell is [PHONE].`

</details>

<details><summary>T03</summary>

- **1** `Help moving furniture` / `Moving out on Saturday, need two people to help lift a couch. Text [PHONE].`
- **2** `Help moving furniture` / `Moving out on Saturday, need two people to help lift a couch. Text [PHONE].`
- **4** `Help moving furniture` / `Moving out on Saturday, need two people to help lift a couch. Text [PHONE].`

</details>

<details><summary>T04</summary>

- **1** `Tutoring for my son` / `Looking for a math tutor for 8th grade. Reach me on [PHONE] or WhatsApp.`
- **2** `Tutoring for my son` / `Looking for a math tutor for 8th grade. Reach me on [PHONE] or WhatsApp.`
- **4** `Tutoring for my son` / `Looking for a math tutor for 8th grade. Reach me on [PHONE] or WhatsApp.`

</details>

<details><summary>T05</summary>

- **1** `Need help with rent` / `Lost my job last month. My number in India is +91 98765 43210, I am visiting family.`  
  not caught: +91 98765 43210 (missed)
- **2** `Need help with rent` / `Lost my job last month. My number in India is +91 98765 43210, I am visiting family.`  
  not caught: +91 98765 43210 (missed)
- **4** `Need help with rent` / `Lost my job last month. My number in India is [PHONE], I am visiting family.`

</details>

<details><summary>T06</summary>

- **1** `Medicine pickup` / `Can someone pick up my prescription? Call my home line 555-0199.`  
  not caught: 555-0199 (missed)
- **2** `Medicine pickup` / `Can someone pick up my prescription? Call my home line 555-0199.`  
  not caught: 555-0199 (missed)
- **4** `Medicine pickup` / `Can someone pick up my prescription? Call my home line [PHONE].`

</details>

<details><summary>T07</summary>

- **1** `Help with job application` / `I need help filling online forms. My phone is four zero eight five five five zero one nine two.`  
  not caught: four zero eight five five five zero one nine two (missed)
- **2** `Help with job application` / `I need help filling online forms. My phone is four zero eight five five five zero one nine two.`  
  not caught: four zero eight five five five zero one nine two (missed)
- **4** `Help with job application` / `I need help filling online forms. My phone is [PHONE].`

</details>

<details><summary>T08</summary>

- **1** `Food for family of five` / `Please contact 408 five five five 0161 when food is ready, thank you.`  
  not caught: 408 five five five 0161 (missed)
- **2** `Food for family of five` / `Please contact 408 five five five 0161 when food is ready, thank you.`  
  not caught: 408 five five five 0161 (missed)
- **4** `Food for family of five` / `Please contact [PHONE] when food is ready, thank you.`

</details>

<details><summary>T09</summary>

- **1** `Translator needed` / `Need a Spanish translator for a school meeting. UK number while abroad: +44 20 7946 0958.`  
  not caught: +44 20 7946 0958 (missed)
- **2** `Translator needed` / `Need a Spanish translator for a school meeting. UK number while abroad: +44 20 7946 0958.`  
  not caught: +44 20 7946 0958 (missed)
- **4** `Translator needed` / `Need a Spanish translator for a school meeting. UK number while abroad: [PHONE].`

</details>

<details><summary>T10</summary>

- **1** `Wheelchair ramp` / `Need a ramp built at the front door. Phone [PHONE] ext. 12.`
- **2** `Wheelchair ramp` / `Need a ramp built at the front door. Phone [PHONE] ext. 12.`
- **4** `Wheelchair ramp` / `Need a ramp built at the front door. Phone [PHONE] ext. 12.`

</details>

<details><summary>T11</summary>

- **1** `Laptop for school` / `My daughter needs a laptop for online classes. Email me at [EMAIL]`
- **2** `Laptop for school` / `My daughter needs a laptop for online classes. Email me at [EMAIL]`
- **4** `Laptop for school` / `My daughter needs a laptop for online classes. Email me at [NAME]`

</details>

<details><summary>T12</summary>

- **1** `Resume review` / `Please send feedback to raghu dot priya at gmail dot com, I check it daily.`  
  not caught: raghu dot priya at gmail dot com (missed)
- **2** `Resume review` / `Please send feedback to raghu dot priya at gmail dot com, I check it daily.`  
  not caught: raghu dot priya at gmail dot com (missed)
- **4** `Resume review` / `Please send feedback to [EMAIL], I check it daily.`

</details>

<details><summary>T13</summary>

- **1** `Winter clothes` / `Need jackets for two kids. You can write to kwame_m [at] example [dot] org.`  
  not caught: kwame_m [at] example [dot] org (missed)
- **2** `Winter clothes` / `Need jackets for two kids. You can write to kwame_m [at] example [dot] org.`  
  not caught: kwame_m [at] example [dot] org (missed)
- **4** `Winter clothes` / `Need jackets for two kids. You can write to [EMAIL].`

</details>

<details><summary>T14</summary>

- **1** `Contact me by email` / `Email: [EMAIL]`
- **2** `Contact me by email` / `Email: [EMAIL]`
- **4** `Contact me by email` / `Email: [NAME]`

</details>

<details><summary>T15</summary>

- **1** `Groceries for Maria Lopez` / `Maria Lopez is my neighbour and cannot walk to the store.`  
  not caught: Maria Lopez (missed), Maria Lopez (missed)
- **2** `Groceries for [NAME] [NAME]` / `[NAME] [NAME] is my neighbour and cannot walk to the store.`
- **4** `Groceries for [NAME]` / `[NAME] is my neighbour and cannot walk to the store.`

</details>

<details><summary>T16</summary>

- **1** `Help for elderly father` / `My father José Hernández needs someone to check on him twice a week.`  
  not caught: José Hernández (missed)
- **2** `Help for elderly father` / `My father [NAME] [NAME] needs someone to check on him twice a week.`
- **4** `Help for elderly father` / `My father [NAME] needs someone to check on him twice a week.`

</details>

<details><summary>T17</summary>

- **1** `Need a ride` / `Hi, this is Oluwaseun Adeyemi. I need a ride to the DMV on Monday.`  
  not caught: Oluwaseun Adeyemi (missed)
- **2** `Need a ride` / `Hi, this is [NAME] [NAME]. I need a ride to the DMV on Monday.`
- **4** `Need a ride` / `Hi, this is [NAME]. I need a ride to the DMV on Monday.`

</details>

<details><summary>T18</summary>

- **1** `Meal delivery` / `Please deliver meals to Mohammed Al-Rashid, he just had surgery.`  
  not caught: Mohammed Al-Rashid (missed)
- **2** `Meal delivery` / `Please deliver meals to [NAME] [NAME], he just had surgery.`
- **4** `Meal delivery` / `Please deliver meals to [NAME], he just had surgery.`

</details>

<details><summary>T19</summary>

- **1** `Help with English classes` / `I am Nguyễn Thị Lan and I want to learn English to find work.`  
  not caught: Nguyễn Thị Lan (missed)
- **2** `Help with English classes` / `I am [NAME] [NAME] [NAME] and I want to learn English to find work.`
- **4** `Help with English classes` / `I am [NAME] and I want to learn English to find work.`

</details>

<details><summary>T20</summary>

- **1** `Babysitting` / `Need babysitting on Tuesday evening. Ask for Fatima Zahra Benali at the front desk.`  
  not caught: Fatima Zahra Benali (missed)
- **2** `Babysitting` / `Need babysitting on Tuesday evening. Ask for [NAME] [NAME] [NAME] at the front desk.`
- **4** `Babysitting` / `Need babysitting on Tuesday evening. Ask for [NAME] at the front desk.`

</details>

<details><summary>T21</summary>

- **1** `Computer help` / `My grandmother Aiko Tanaka needs help setting up video calls with family.`  
  not caught: Aiko Tanaka (missed)
- **2** `Computer help` / `My grandmother [NAME] [NAME] needs help setting up video calls with family.`
- **4** `Computer help` / `My grandmother [NAME] needs help setting up video calls with family.`

</details>

<details><summary>T22</summary>

- **1** `Food assistance` / `my name is guadalupe ramírez and we need food for this week`  
  not caught: guadalupe ramírez (missed)
- **2** `Food assistance` / `my name is guadalupe ramírez and we need food for this week`  
  not caught: guadalupe ramírez (missed)
- **4** `Food assistance` / `my name is [NAME] and we need food for this week`

</details>

<details><summary>T23</summary>

- **1** `Yard cleanup` / `Chinedu Okafor here, need help clearing fallen branches after the storm.`  
  not caught: Chinedu Okafor (missed)
- **2** `Yard cleanup` / `[NAME] [NAME] here, need help clearing fallen branches after the storm.`
- **4** `Yard cleanup` / `[NAME] here, need help clearing fallen branches after the storm.`

</details>

<details><summary>T24</summary>

- **1** `Hospital visit company` / `Lakshmi Narayanan would like someone to sit with her during dialysis.`  
  not caught: Lakshmi Narayanan (missed)
- **2** `Hospital visit company` / `[NAME] [NAME] would like someone to sit with her during dialysis.`
- **4** `Hospital visit company` / `[NAME] would like someone to sit with her during dialysis.`

</details>

<details><summary>T25</summary>

- **1** `Bike repair` / `Need my bike fixed to get to work. Thanks, Björn Lindqvist`  
  not caught: Björn Lindqvist (missed)
- **2** `Bike repair` / `Need my bike fixed to get to work. Thanks, [NAME] [NAME]`
- **4** `Bike repair` / `Need my bike fixed to get to work. Thanks, [NAME]`

</details>

<details><summary>T26</summary>

- **1** `School supplies` / `Ms. Siddiqui, my son's teacher, said he needs a calculator. Please contact Ayesha Siddiqui (me).`  
  not caught: Siddiqui (missed), Ayesha Siddiqui (missed)
- **2** `School supplies` / `Ms. [NAME], my son's teacher, said he needs a calculator. Please contact [NAME] [NAME] (me).`
- **4** `School supplies` / `Ms. [NAME], my son's teacher, said he needs a calculator. Please contact [NAME] (me).`

</details>

<details><summary>T27</summary>

- **1** `Moving boxes` / `Dmitri Volkov needs boxes and tape for a move next week.`  
  not caught: Dmitri Volkov (missed)
- **2** `Moving boxes` / `[NAME] [NAME] needs boxes and tape for a move next week.`
- **4** `Moving boxes` / `[NAME] needs boxes and tape for a move next week.`

</details>

<details><summary>T28</summary>

- **1** `Help for Siobhán` / `Siobhán Ní Bhriain broke her arm and needs help with shopping.`  
  not caught: Siobhán (missed), Siobhán Ní Bhriain (missed)
- **2** `Help for [NAME]` / `[NAME] Ní [NAME] broke her arm and needs help with shopping.`  
  not caught: Siobhán Ní Bhriain (partial)
- **4** `Help for [NAME]` / `[NAME] broke her arm and needs help with shopping.`

</details>

<details><summary>T29</summary>

- **1** `Thai interpreter` / `Need a Thai speaker to help Anan Srisuk talk to his landlord.`  
  not caught: Anan Srisuk (missed)
- **2** `Thai interpreter` / `Need a Thai speaker to help [NAME] [NAME] talk to his landlord.`
- **4** `Thai interpreter` / `Need a Thai speaker to help [NAME] talk to his landlord.`

</details>

<details><summary>T30</summary>

- **1** `Grocery run` / `Thandiwe Dlamini cannot drive this month, needs weekly groceries.`  
  not caught: Thandiwe Dlamini (missed)
- **2** `Grocery run` / `[NAME] [NAME] cannot drive this month, needs weekly groceries.`
- **4** `Grocery run` / `[NAME] cannot drive this month, needs weekly groceries.`

</details>

<details><summary>T31</summary>

- **1** `Visit my mother` / `My mother Rosa Delgado lives alone and needs someone to visit on weekends.`  
  not caught: Rosa Delgado (missed)
- **2** `Visit my mother` / `My mother Rosa Delgado lives alone and needs someone to visit on weekends.`  
  not caught: Rosa Delgado (missed)
- **4** `Visit my mother` / `My mother [NAME] lives alone and needs someone to visit on weekends.`

</details>

<details><summary>T32</summary>

- **1** `Help my neighbor` / `My neighbor Mr. Haruto Sato fell last week and needs help with groceries.`  
  not caught: Haruto Sato (missed)
- **2** `Help my neighbor` / `My neighbor Mr. Haruto Sato fell last week and needs help with groceries.`  
  not caught: Haruto Sato (missed)
- **4** `Help my neighbor` / `My neighbor [NAME]. [NAME] fell last week and needs help with groceries.`

</details>

<details><summary>T33</summary>

- **1** `Caseworker follow-up` / `Our caseworker Emily Carter said to post here for diapers and formula.`  
  not caught: Emily Carter (missed)
- **2** `Caseworker follow-up` / `Our caseworker Emily Carter said to post here for diapers and formula.`  
  not caught: Emily Carter (missed)
- **4** `Caseworker follow-up` / `Our caseworker [NAME] said to post here for diapers and formula.`

</details>

<details><summary>T34</summary>

- **1** `Landlord dispute` / `Need advice. Landlord Viktor Petrenko wants to evict us without notice.`  
  not caught: Viktor Petrenko (missed)
- **2** `Landlord dispute` / `Need advice. Landlord Viktor Petrenko wants to evict us without notice.`  
  not caught: Viktor Petrenko (missed)
- **4** `Landlord dispute` / `Need advice. Landlord [NAME] wants to evict us without notice.`

</details>

<details><summary>T35</summary>

- **1** `Pet care` / `Please walk our dog while my husband Ikenna is in hospital.`  
  not caught: Ikenna (missed)
- **2** `Pet care` / `Please walk our dog while my husband Ikenna is in hospital.`  
  not caught: Ikenna (missed)
- **4** `Pet care` / `Please walk our dog while my husband [NAME] is in hospital.`

</details>

<details><summary>T36</summary>

- **1** `Food delivery needed` / `Please drop off the food at 1234 Oak Street, Apt 4B. Ring the bell twice.`  
  not caught: 1234 Oak Street, Apt 4B (missed)
- **2** `Food delivery needed` / `Please drop off the food at 1234 Oak Street, Apt 4B. Ring the bell twice.`  
  not caught: 1234 Oak Street, Apt 4B (missed)
- **4** `Food delivery needed` / `Please drop off the food at [ADDRESS]. Ring the bell twice.`

</details>

<details><summary>T37</summary>

- **1** `Snow shoveling` / `Driveway at 77 Maple Ave needs shoveling before Monday morning.`  
  not caught: 77 Maple Ave (missed)
- **2** `Snow shoveling` / `Driveway at 77 Maple Ave needs shoveling before Monday morning.`  
  not caught: 77 Maple Ave (missed)
- **4** `Snow shoveling` / `Driveway at [ADDRESS] needs shoveling before Monday morning.`

</details>

<details><summary>T38</summary>

- **1** `Mail pickup` / `I am traveling, please collect mail from PO Box 2210 for me.`  
  not caught: PO Box 2210 (missed)
- **2** `Mail pickup` / `I am traveling, please collect mail from PO Box 2210 for me.`  
  not caught: PO Box 2210 (missed)
- **4** `Mail pickup` / `I am traveling, please collect mail from [NAME] for me.`

</details>

<details><summary>T39</summary>

- **1** `Ride to work` / `Pick me up from 4521 Stevens Creek Blvd, San Jose at 7am.`  
  not caught: 4521 Stevens Creek Blvd (missed)
- **2** `Ride to work` / `Pick me up from 4521 Stevens Creek Blvd, San [NAME] at 7am.`  
  not caught: 4521 Stevens Creek Blvd (missed)
- **4** `Ride to work` / `Pick me up from [ADDRESS], [NAME] at 7am.`

</details>

<details><summary>T40</summary>

- **1** `Fix leaking sink` / `Our sink is leaking. We live at the blue house on twelve Elm Road.`  
  not caught: twelve Elm Road (missed)
- **2** `Fix leaking sink` / `Our sink is leaking. We live at the blue house on twelve Elm Road.`  
  not caught: twelve Elm Road (missed)
- **4** `Fix leaking sink` / `Our sink is leaking. We live at the blue house on [ADDRESS]`

</details>

<details><summary>T41</summary>

- **1** `Help with benefits form` / `The form asks for my SSN [SSN], can someone help me fill it in?`
- **2** `Help with benefits form` / `The form asks for my SSN [SSN], can someone help me fill it in?`
- **4** `Help with benefits form` / `The form asks for my SSN [ID], can someone help me fill it in?`

</details>

<details><summary>T42</summary>

- **1** `Pay electricity bill` / `Can someone pay my bill? My card is [CARD].`
- **2** `Pay electricity bill` / `Can someone pay my bill? My card is [CARD].`
- **4** `Pay electricity bill` / `Can someone pay my bill? My card is [CARD].`

</details>

<details><summary>T43</summary>

- **1** `Find me online` / `You can message me on [URL] for details.`
- **2** `Find me online` / `You can message me on [URL] for details.`
- **4** `Find me online` / `You can message me on [URL] for details.`

</details>

<details><summary>T44</summary>

- **1** `Urgent: food and diapers` / `This is Carmen Ruiz, call [PHONE] or email [EMAIL] Address is 89 Pine Lane.`  
  not caught: Carmen Ruiz (missed), 89 Pine Lane (missed)
- **2** `Urgent: food and diapers` / `This is [NAME] [NAME], call [PHONE] or email [EMAIL] Address is 89 Pine Lane.`  
  not caught: 89 Pine Lane (missed)
- **4** `Urgent: food and diapers` / `This is [NAME], call [PHONE] or email [NAME] Address is [ADDRESS]`

</details>

<details><summary>T45</summary>

- **1** `Help for Wei Zhang` / `Wei Zhang needs a ride to the airport. His number is [PHONE].`  
  not caught: Wei Zhang (missed), Wei Zhang (missed)
- **2** `Help for [NAME] [NAME]` / `[NAME] [NAME] needs a ride to the airport. His number is [PHONE].`
- **4** `Help for [NAME]` / `[NAME] needs a ride to the airport. His number is [PHONE].`

</details>

<details><summary>T46</summary>

- **1** `Need help with taxes` / `Rahul Verma, [EMAIL], [PHONE]. Need help with tax filing.`  
  not caught: Rahul Verma (missed)
- **2** `Need help with taxes` / `[NAME] [NAME], [EMAIL], [PHONE]. Need help with tax filing.`
- **4** `Need help with taxes` / `[NAME], [EMAIL], [PHONE]. Need help with tax filing.`

</details>

<details><summary>T47</summary>

- **1** `Donation pickup` / `Yusuf Demir has a sofa to donate, pick up at 300 Bay Road. Call five one zero, five five five, zero one four four.`  
  not caught: Yusuf Demir (missed), 300 Bay Road (missed), five one zero, five five five, zero one four four (missed)
- **2** `Donation pickup` / `[NAME] [NAME] has a sofa to donate, pick up at 300 Bay Road. Call five one zero, five five five, zero one four four.`  
  not caught: 300 Bay Road (missed), five one zero, five five five, zero one four four (missed)
- **4** `Donation pickup` / `[NAME] has a sofa to donate, pick up at [ADDRESS] Call [PHONE].`

</details>

<details><summary>T48</summary>

- **1** `Need a ride for Grace` / `Grace Thompson needs a ride to church on Sunday, call [PHONE].`  
  not caught: Grace (missed), Grace Thompson (missed)
- **2** `Need a ride for [NAME]` / `[NAME] [NAME] needs a ride to church on Sunday, call [PHONE].`
- **4** `Need a ride for [NAME]` / `[NAME] needs a ride to church on Sunday, call [PHONE].`

</details>

<details><summary>T49</summary>

- **1** `Hope needs a coat` / `Hope Williams needs a winter coat, size M.`  
  not caught: Hope (missed), Hope Williams (missed)
- **2** `[NAME] needs a coat` / `[NAME] [NAME] needs a winter coat, size M.`
- **4** `Hope needs a coat` / `[NAME] needs a winter coat, size M.`  
  not caught: Hope (missed)

</details>

<details><summary>T50</summary>

- **1** `Help Jordan move` / `Jordan Brooks is moving to a new apartment and needs a truck.`  
  not caught: Jordan (missed), Jordan Brooks (missed)
- **2** `Help [NAME] move` / `[NAME] [NAME] is moving to a new apartment and needs a truck.`
- **4** `Help [NAME] move` / `[NAME] is moving to a new apartment and needs a truck.`

</details>

<details><summary>C01</summary>

- **1** `Groceries for a family of four` / `We need rice, beans, milk and vegetables for this week.`
- **2** `Groceries for a family of four` / `We need rice, beans, milk and vegetables for this week.`
- **4** `Groceries for a family of four` / `We need rice, beans, milk and vegetables for this week.`

</details>

<details><summary>C02</summary>

- **1** `Rent help` / `Rent of $1,250 is due on 11/15/2026 and I am short by $400.`
- **2** `Rent help` / `Rent of $1,250 is due on 11/15/2026 and I am short by $400.`
- **4** `Rent help` / `Rent of $1,250 is due on 11/15/2026 and I am short by $400.`

</details>

<details><summary>C03</summary>

- **1** `Childcare` / `I have 3 kids aged 4, 7 and 12 and need after-school care twice a week.`
- **2** `Childcare` / `I have 3 kids aged 4, 7 and 12 and need after-school care twice a week.`
- **4** `Childcare` / `I have 3 kids aged 4, 7 and 12 and need after-school care twice a week.`

</details>

<details><summary>C04</summary>

- **1** `Emergency info` / `If it is an emergency please call 911. Otherwise any time this week is fine.`
- **2** `Emergency info` / `If it is an emergency please call 911. Otherwise any time this week is fine.`
- **4** `Emergency info` / `If it is an emergency please call 911. Otherwise any time this week is fine.`

</details>

<details><summary>C05</summary>

- **1** `Grace period ended` / `The grace period on my rent ended and I need help paying it.`
- **2** `[NAME] period ended` / `The grace period on my rent ended and I need help paying it.`
- **4** `Grace period ended` / `The grace period on my rent ended and I need help paying it.`

</details>

<details><summary>C06</summary>

- **1** `Hope to find work` / `Hope someone can help me write a cover letter. Will pay it forward.`
- **2** `[NAME] to find work` / `[NAME] someone can help me write a cover letter. Will pay it forward.`
- **4** `Hope to find work` / `Hope someone can help me write a cover letter. Will pay it forward.`

</details>

<details><summary>C07</summary>

- **1** `Clinic on Mission Blvd` / `Need a ride to the free clinic on Mission Blvd in Fremont.`
- **2** `Clinic on Mission Blvd` / `Need a ride to the free clinic on Mission Blvd in Fremont.`
- **4** `Clinic on Mission Blvd` / `Need a ride to the free clinic on Mission Blvd in Fremont.`

</details>

<details><summary>C08</summary>

- **1** `Help after flood` / `Our basement flooded during the storm. Need help moving things upstairs.`
- **2** `Help after flood` / `Our basement flooded during the storm. Need help moving things upstairs.`
- **4** `Help after flood` / `Our basement flooded during the storm. Need help moving things upstairs.`

</details>

<details><summary>C09</summary>

- **1** `Food bank information` / `Where is the nearest food bank? I saw [URL] but could not find one.`
- **2** `Food bank information` / `Where is the nearest food bank? I saw [URL] but could not find one.`
- **4** `Food bank information` / `Where is the nearest food bank? I saw [URL] but could not find one.`

</details>

<details><summary>C10</summary>

- **1** `Refugee family from Jordan` / `A family that just arrived from Jordan needs furniture and kitchen items.`
- **2** `Refugee family from [NAME]` / `A family that just arrived from [NAME] needs furniture and kitchen items.`
- **4** `Refugee family from [NAME]` / `A family that just arrived from [NAME] needs furniture and kitchen items.`

</details>

<details><summary>C11</summary>

- **1** `Laptop repair` / `My laptop model 15-ay041wm will not turn on. Need someone who knows computers.`
- **2** `Laptop repair` / `My laptop model 15-ay041wm will not turn on. Need someone who knows computers.`
- **4** `Laptop repair` / `My laptop model 15-ay041wm will not turn on. Need someone who knows computers.`

</details>

<details><summary>C12</summary>

- **1** `Bus pass` / `Need a monthly bus pass for route 22 to get to my new job.`
- **2** `Bus pass` / `Need a monthly bus pass for route 22 to get to my new job.`
- **4** `Bus pass` / `Need a monthly bus pass for route 22 to get to my new job.`

</details>

<details><summary>C13</summary>

- **1** `Medicine` / `I take 2 pills a day and the pharmacy is closed on Sunday.`
- **2** `Medicine` / `I take 2 pills a day and the pharmacy is closed on Sunday.`
- **4** `Medicine` / `I take 2 pills a day and the pharmacy is closed on Sunday.`

</details>

<details><summary>C14</summary>

- **1** `Tutoring` / `Looking for a chemistry tutor, high school level, 2 hours per week.`
- **2** `Tutoring` / `Looking for a chemistry tutor, high school level, 2 hours per week.`
- **4** `Tutoring` / `Looking for a chemistry tutor, high school level, 2 hours per week.`

</details>

<details><summary>C15</summary>

- **1** `Wheelchair` / `Need a used wheelchair, budget under 150 dollars.`
- **2** `Wheelchair` / `Need a used wheelchair, budget under 150 dollars.`
- **4** `Wheelchair` / `Need a used wheelchair, budget under 150 dollars.`

</details>

<details><summary>C16</summary>

- **1** `Tax help` / `I need help with my 2025 tax return and form 1040.`
- **2** `Tax help` / `I need help with my 2025 tax return and form 1040.`
- **4** `Tax help` / `I need help with my 2025 tax return and form 1040.`

</details>

<details><summary>C17</summary>

- **1** `Phone plan` / `My phone was cut off. Need help finding a cheap phone plan.`
- **2** `Phone plan` / `My phone was cut off. Need help finding a cheap phone plan.`
- **4** `Phone plan` / `My phone was cut off. Need help finding a cheap phone plan.`

</details>

<details><summary>C18</summary>

- **1** `Help at Lincoln Elementary` / `Volunteers needed to paint the fence at Lincoln Elementary on Saturday.`
- **2** `Help at Lincoln Elementary` / `Volunteers needed to paint the fence at Lincoln Elementary on Saturday.`
- **4** `Help at Lincoln Elementary` / `Volunteers needed to paint the fence at Lincoln Elementary on Saturday.`

</details>

<details><summary>C19</summary>

- **1** `May food drive` / `May I get a box from the food drive? We are a family of 6.`
- **2** `May food drive` / `May I get a box from the food drive? We are a family of 6.`
- **4** `May food drive` / `May I get a box from the food drive? We are a family of 6.`

</details>

<details><summary>C20</summary>

- **1** `Order tracking` / `Donated items were shipped, tracking number 1Z999AA[PHONE].`
- **2** `Order tracking` / `Donated items were shipped, tracking number 1Z999AA[PHONE].`
- **4** `Order tracking` / `Donated items were shipped, tracking number 1Z999AA[PHONE].`

</details>

