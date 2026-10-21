# Emergency Contact Test Results - Issue #482

**Date:** 2026-10-19

**Tester:** omsali (GitHub username)

**Environment:** Chrome 150 / VS Code integrated browser on Windows (Windows NT 10.0). Exact Windows version, network type, and VPN state are unknown. Browser geolocation permission was granted for the initial real-location observation. Country scenarios used the test plan coordinates through a temporary browser geolocation override.

**Tracker:** [issue_482_test_tracker.md](issue_482_test_tracker.md)

## A1: Current Browser Location

Observed: `Area Detected: Chicago, Illinois (US)`; Police 911, Fire 911, Medical 911, Ambulance 911, Mental Health 988, Suicide Prevention 988. The browser reported geolocation permission as granted. The tester's physical location could not be independently confirmed, so A1 is Partial pending confirmation.

## B1-B23: Country Scenarios

Each scenario matched its expected country code and all six displayed contact rows. In the rows below, values are ordered Police / Fire / Medical / Ambulance / Mental Health / Suicide Prevention.

| ID | Area detected | Actual values | Result |
| --- | --- | --- | --- |
| B1 | New Delhi, Delhi (IN) | 112 / 101 / 108 / 108 / 9152987821 / 9152987821 | Pass |
| B2 | لیاری ٹاؤن, سندھ (PK) | 15 / 16 / 1122 / 1122 / 15 / 15 | Pass |
| B3 | Dubai, Dubai (AE) | 999 / 997 / 998 / 998 / 999 / 999 | Pass |
| B4 | 杉並区, null (JP) | 110 / 119 / 119 / 119 / 110 / 110 | Pass for numbers/country; C6 Fail |
| B5 | Singapore, null (SG) | 999 / 995 / 995 / 995 / 999 / 999 | Pass for numbers/country; C6 Fail |
| B6 | Manila, null (PH) | 911 / 911 / 911 / 911 / 911 / 911 | Pass for numbers/country; C6 Fail |
| B7 | Istanbul, null (TR) | 155 / 112 / 112 / 112 / 112 / 112 | Pass for numbers/country; C6 Fail |
| B8 | القاهرة, القاهرة (EG) | 122 / 180 / 123 / 123 / 112 / 112 | Pass |
| B9 | City of Westminster, England (GB) | 999 / 999 / 999 / 999 / 999 / 999 | Pass |
| B10 | Paris, Ile-de-France (FR) | 17 / 18 / 15 / 15 / 112 / 112 | Pass |
| B11 | Berlin, null (DE) | 110 / 112 / 112 / 112 / 112 / 112 | Pass for numbers/country; C6 Fail |
| B12 | Bern, Bern/Berne (CH) | 117 / 118 / 144 / 144 / 117 / 117 | Pass |
| B13 | Kyiv, null (UA) | 102 / 101 / 103 / 103 / 112 / 112 | Pass for numbers/country; C6 Fail |
| B14 | Bariga, Lagos (NG) | 112 / 112 / 112 / 112 / 112 / 112 | Pass |
| B15 | Nairobi, Nairobi (KE) | 112 / 112 / 112 / 112 / 112 / 112 | Pass |
| B16 | Johannesburg, Gauteng (ZA) | 10111 / 10177 / 10177 / 10177 / 10111 / 10111 | Pass |
| B17 | New York, New York (US) | 911 / 911 / 911 / 911 / 988 / 988 | Pass |
| B18 | Toronto, Ontario (CA) | 911 / 911 / 911 / 911 / 988 / 988 | Pass |
| B19 | Ciudad de México, Ciudad de México (MX) | 911 / 911 / 911 / 911 / 911 / 911 | Pass |
| B20 | São Paulo, São Paulo (BR) | 190 / 193 / 192 / 192 / 190 / 190 | Pass |
| B21 | Bogotá ciudad, Bogotá, Distrito Capital (CO) | 112 / 119 / 125 / 125 / 123 / 123 | Pass |
| B22 | Sydney, New South Wales (AU) | 000 / 000 / 000 / 000 / 131114 / 131114 | Pass |
| B23 | Bengaluru, Karnataka (IN) | 112 / 101 / 108 / 108 / 9152987821 / 9152987821 | Pass |

## C1: Unavailable Geographic Data

Set geolocation to Antarctica (`-75, 0`). The page did not crash and fell back to `Chicago, Illinois (US)` with US numbers. This is consistent with the observed US egress; no exact IP or coordinates were recorded.

## C2: Logged-Out Access

While logged out, the page briefly displayed default US contacts, then an API request returned 401 and the browser redirected to login. This matches the known behavior noted by the task.

## C3: Offline Reload

With the browser context offline, reloading produced Chrome's `ERR_INTERNET_DISCONNECTED` error page rather than the app's default-contact fallback. Connectivity was restored after the test.

## C5: Repeatability

Reloaded the Paris scenario ten times. Every load showed the same area and six values. A reCAPTCHA resource error appeared elsewhere in the browser session; console output was not exhaustively audited for each reload, so this result covers output stability only.

## C6: Area Label Defect

**Fail - Medium.** B4 Tokyo, B5 Singapore, B6 Manila, B7 Istanbul, B11 Berlin, and B13 Kyiv each displayed a literal `null` in the state portion of `Area Detected`. All six country codes and emergency-contact values were correct. This reproduces the C6 defect described in the existing tracker.

## D1-D2: Request Details and Navigation

- **D1 Pass:** Opened an existing Super Admin request and selected Emergency Contacts. It displayed the same Chicago/US area and values as the standalone page. Request identifiers and personal details are intentionally omitted.
- **D2 Pass:** The standalone page's Back to Dashboard button navigated to `/dashboard`.

## Blocked or Not Tested

- A2-A7: permission state cannot be changed by this browser automation; no OS-location, Ethernet, or VPN setup was performed.
- D3-D6: no physical phone or alternate browser was available; language switch was not assessed.
- E1-E9: direct API checks were not run because the browser request helper could not access session cookies. No token was copied or shared.
- C4: network throttling was not available.

No screenshots were attached, and these results have not been posted to the shared GitHub tracker. Confirm any location-dependent details and have the task lead review the C6 defect before treating the QA task as complete.