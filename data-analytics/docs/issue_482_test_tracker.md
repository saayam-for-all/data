# Emergency Contact QA Tracker - Issue #482

**Volunteer:** omsali (GitHub username)

**Date:** 2026-10-19

**Environment:** Chrome 150 / VS Code integrated browser on Windows (Windows NT 10.0); exact Windows version, network type, and VPN state not available. Country scenarios used the documented coordinates through the browser geolocation test context.

**Evidence report:** [issue_482_test_results.md](issue_482_test_results.md)

Status legend: Pass = observed and matched expected; Fail = observed mismatch; Partial = only part of the case was verified; Blocked = could not be performed in this environment; Not tested = not attempted.

## A. Location Detection

| ID | Status | Notes |
| --- | --- | --- |
| A1 | Partial | Browser permission was granted; page showed Chicago, Illinois (US) and US numbers. Physical-location accuracy could not be confirmed. |
| A2 | Blocked | Browser automation does not support changing geolocation permission state. |
| A3 | Blocked | Could not leave a browser location-permission prompt unanswered with this browser tool. |
| A4 | Blocked | Did not change Windows location settings. |
| A5 | Blocked | Ethernet with Wi-Fi disabled was not available to verify. |
| A6 | Blocked | VPN-denied-location scenario was not available. |
| A7 | Blocked | VPN-allowed-location scenario was not available. |

## B. Country and Regional Numbers

| ID | Location | Status | Notes |
| --- | --- | --- | --- |
| B1 | New Delhi, IN | Pass | Expected numbers and country code. |
| B2 | Karachi, PK | Pass | Expected numbers and country code. |
| B3 | Dubai, AE | Pass | Expected numbers and country code. |
| B4 | Tokyo, JP | Pass / C6 Fail | Numbers and country code matched; state displayed literal `null`. |
| B5 | Singapore, SG | Pass / C6 Fail | Numbers and country code matched; state displayed literal `null`. |
| B6 | Manila, PH | Pass / C6 Fail | Numbers and country code matched; state displayed literal `null`. |
| B7 | Istanbul, TR | Pass / C6 Fail | Numbers and country code matched; state displayed literal `null`. |
| B8 | Cairo, EG | Pass | Expected numbers and country code. |
| B9 | London, GB | Pass | Expected numbers and country code. |
| B10 | Paris, FR | Pass | Expected numbers and country code. |
| B11 | Berlin, DE | Pass / C6 Fail | Numbers and country code matched; state displayed literal `null`. |
| B12 | Bern, CH | Pass | Expected numbers and country code. |
| B13 | Kyiv, UA | Pass / C6 Fail | Numbers and country code matched; state displayed literal `null`. |
| B14 | Lagos, NG | Pass | Expected numbers and country code. |
| B15 | Nairobi, KE | Pass | Expected numbers and country code. |
| B16 | Johannesburg, ZA | Pass | Expected numbers and country code. |
| B17 | New York, US | Pass | Expected numbers and country code. |
| B18 | Toronto, CA | Pass | Expected numbers and country code. |
| B19 | Mexico City, MX | Pass | Expected numbers and country code. |
| B20 | Sao Paulo, BR | Pass | Expected numbers and country code. |
| B21 | Bogota, CO | Pass | Expected numbers and country code. |
| B22 | Sydney, AU | Pass | Expected numbers and country code. |
| B23 | Bengaluru, Karnataka, IN | Pass | Expected numbers, country code, and Karnataka state. |

## C. Errors and Unusual Situations

| ID | Status | Notes |
| --- | --- | --- |
| C1 | Pass | Antarctica coordinates fell back to Chicago/US numbers without crashing; egress was US. |
| C2 | Pass with known issue | Logged-out page briefly showed default US contacts, then returned 401 and redirected to login. |
| C3 | Fail / known issue | Offline reload displayed Chrome `ERR_INTERNET_DISCONNECTED` instead of the app's default-contact fallback. Connectivity was restored afterward. |
| C4 | Blocked | Slow-4G network throttling was not available. |
| C5 | Partial | Ten reloads returned identical Paris results. Console errors were not exhaustively checked; a reCAPTCHA resource error appeared during the browser session. |
| C6 | Fail - Medium | B4, B5, B6, B7, B11, and B13 display literal `null` as the state. Country codes and numbers are correct. |

## D. Pages, Browsers, and Devices

| ID | Status | Notes |
| --- | --- | --- |
| D1 | Pass | Super Admin All Requests -> Request Details -> Emergency Contacts matched standalone US area and numbers. Request identifiers/details are omitted from this report. |
| D2 | Pass | Standalone Back to Dashboard navigated to `/dashboard`. |
| D3 | Blocked | No phone/dialer device available. |
| D4 | Blocked | Firefox, Safari, and Edge were not available in this browser session. |
| D5 | Blocked | No phone available for portrait/landscape testing. |
| D6 | Not tested | Language-switch control was not tested. |

## E. Optional API Checks

| ID | Status | Notes |
| --- | --- | --- |
| E1-E9 | Blocked | Direct API checks were not run. The browser request helper could not access session cookies; no auth token was copied or shared. |

## Overall

This is a partial test run, not completion of issue #482. B1-B23 were verified in Chrome, but location-permission/network/device cases remain blocked, C6 is a Medium failure, and the results still need to be entered into the shared tracker/reviewed by the task lead.