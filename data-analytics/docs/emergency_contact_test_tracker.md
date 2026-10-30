# Emergency Contact Testing Tracker (Issue #482)

Test plan: https://github.com/saayam-for-all/data/issues/482
Expected values: `data-engineering/datasets/raw/emergency_contacts_expected_values.csv`

**Legend:** `[x]` = test run and result recorded (a failure is marked **Fail** in its line), `[ ]` = not run yet.

**Volunteer:** Pranav Doshetty
**Environment:** Chrome 152, macOS, Wi-Fi, no VPN. Real location: Sammamish, WA (US). Run date: 2026-10-18.

## A. Location detection

- [x] **A1** (P1) Allow location. Pass: "Sammamish, Washington (US)", 911/911/911/911/988/988.
- [x] **A2** (P1) Block location. Pass (simulated deny): IP fallback, "Bellevue, Washington (US)", US numbers.
- [x] **A3** (P2) No response for 15 s. Pass (simulated): page waits 8 s, then shows IP-country numbers at about 10 s. Does not hang.
- [x] **A4** (P2) OS location off. Pass (simulated unavailable): same IP fallback as A2.
- [ ] **A5** (P2) Ethernet, Wi-Fi off.
- [ ] **A6** (P2) VPN on, location blocked.
- [ ] **A7** (P2) VPN on, location allowed.

## B. Numbers for other countries

All 6 rows match the CSV and the country code in "Area Detected" is correct for every case below. Columns: Police / Fire / Ambulance / Mental health.

- [x] **B1** New Delhi, IN, 112 / 101 / 108 / 9152987821. Area: "New Delhi, Delhi (IN)".
- [x] **B2** Karachi, PK, 15 / 16 / 1122 / 15. Area: "لیاری ٹاؤن, سندھ (PK)".
- [x] **B3** Dubai, AE, 999 / 997 / 998 / 999. Area: "دبي, دبي (AE)".
- [x] **B4** Tokyo, JP, 110 / 119 / 119 / 110. Area: "杉並区, null (JP)" (`null`, see C6).
- [x] **B5** Singapore, SG, 999 / 995 / 995 / 999. Area: "Singapore, null (SG)" (`null`, see C6).
- [x] **B6** Manila, PH, 911 / 911 / 911 / 911. Area: "Manila, null (PH)" (`null`, see C6).
- [x] **B7** Istanbul, TR, 155 / 112 / 112 / 112. Area: "İstanbul, null (TR)" (`null`, see C6).
- [x] **B8** Cairo, EG, 122 / 180 / 123 / 112. Area: "القاهرة, القاهرة (EG)".
- [x] **B9** London, GB, 999 / 999 / 999 / 999. Area: "City of Westminster, England (GB)".
- [x] **B10** Paris, FR, 17 / 18 / 15 / 112. Area: "Paris, Île-de-France (FR)".
- [x] **B11** Berlin, DE, 110 / 112 / 112 / 112. Area: "Berlin, null (DE)" (`null`, see C6).
- [x] **B12** Bern, CH, 117 / 118 / 144 / 117. Area: "Bern, Bern/Berne (CH)".
- [x] **B13** Kyiv, UA, 102 / 101 / 103 / 112. Area: "Київ, null (UA)" (`null`, see C6).
- [x] **B14** Lagos, NG, 112 / 112 / 112 / 112. Area: "Bariga, Lagos (NG)".
- [x] **B15** Nairobi, KE, 112 / 112 / 112 / 112. Area: "Nairobi, Nairobi (KE)".
- [x] **B16** Johannesburg, ZA, 10111 / 10177 / 10177 / 10111. Area: "Johannesburg, Gauteng (ZA)".
- [x] **B17** New York, US, 911 / 911 / 911 / 988. Area: "New York, New York (US)".
- [x] **B18** Toronto, CA, 911 / 911 / 911 / 988. Area: "Toronto, Ontario (CA)".
- [x] **B19** Mexico City, MX, 911 / 911 / 911 / 911. Area: "Ciudad de México, Ciudad de México (MX)".
- [x] **B20** São Paulo, BR, 190 / 193 / 192 / 190. Area: "São Paulo, São Paulo (BR)".
- [x] **B21** Bogotá, CO, 112 / 119 / 125 / 123. Area: "Bogotá ciudad, Bogotá, Distrito Capital (CO)".
- [x] **B22** Sydney, AU, 000 / 000 / 000 / 131114. Area: "Sydney, New South Wales (AU)".
- [x] **B23** Bengaluru, IN (state data), 112 / 101 / 108 / 9152987821. Area shows Karnataka and (IN).

## C. Errors and unusual situations

- [x] **C1** (P1) Antarctica `-75, 0`. Pass: no crash, IP-country numbers (US, so 911/988 is correct).
- [x] **C2** (P1) Logged out. Pass with known issue: the page loads for a split second, then redirects to the login page.
- [x] **C3** (P1) Offline. Pass with known issue (simulated API failure): no crash, shows "Using default emergency numbers - USA".
- [x] **C4** (P2) Slow 4G. Pass: took 21.97 s on Slow 4G vs 3.18 s unthrottled.
- [x] **C5** (P2) Load 10 times. Pass: identical numbers every time, 1–2.5 s each, no errors.
- [x] **C6** (P1) No `undefined` or `null` in "Area Detected". **Fail (Medium).** Re-run for B4, B5, B6, B7, B11 and B13: all six show a literal `null` as the state, e.g. "Singapore, null (SG)", "Berlin, null (DE)". The numbers are correct in all six. Looks like cases where the location lookup returns no state; needs a defect comment on #482.

## D. Pages, browsers and devices

- [x] **D1** (P1) Request ID → Emergency Contacts button. Pass: same area and numbers as the standalone page.
- [x] **D2** (P1) Back to Dashboard. Pass: returns to the Super Admin Dashboard.
- [x] **D3** (P1) Phone dialer opens with the exact number. Done on phone.
- [ ] **D4** (P2) Firefox, Safari, Edge: A1 plus one B case. Safari: A1 works. B cases could not be tested in Safari (no sensor override UI). Firefox and Edge not yet tested.
- [x] **D5** (P2) Phone portrait and landscape. Works as expected in both orientations on iPhone 17 Pro.
- [x] **D6** (P2) Language switch. Works as expected.

## E. API tests

Run with the page's own session token (Authorization header, no `Bearer`).

- [x] **E1** `country=IN`. 200: police 112, ambulance 108, fire 101.
- [x] **E2** `country=PK&service=ambulance`. 200: only ambulance, 1122.
- [x] **E3** `country=CH&service=suicide_helpline`. 200: 117, `is_fallback` true.
- [x] **E4** `country=IN&state=Karnataka&city=Bengaluru`. 200: `match_level` zip (560001), police 112.
- [x] **E5** `lat=48.8566&lng=2.3522`. 200: country FR, police 17.
- [x] **E6** `country=XX`. 404 "Emergency services not found".
- [x] **E7** `country=IN&service=plumber`. 404.
- [x] **E8** `country=IN&service=police&language=hi`. 200: display "११२", dial 112.
- [x] **E9** No Authorization header. 401 Unauthorized.

## Side observations (not test failures)

- Location names can come back in the local language (Karachi, Dubai, Cairo, Tokyo, Kyiv), which the plan accepts.
- The API response includes a `client_ip` field echoing the caller's IP address.
