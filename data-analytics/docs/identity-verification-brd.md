# Identity Verification for Volunteer Onboarding — Business Requirements and Vendor Evaluation

| Field | Value |
|---|---|
| **Title** | Identity Verification for Volunteer Onboarding — BRD and Vendor Evaluation |
| **Authors** | Mohammed Afaan Ansari |
| **Date** | 2026-11-23 |
| **Version** | 0.1 |
| **Status** | Draft |
| **Reviewers** | Saayam leadership; Data / Engineering maintainers (to be assigned) |
| **Related issue** | [#694](https://github.com/saayam-for-all/data/issues/694) |
| **Base branch** | `test` |

---

## 1. Executive summary

**Problem.** Promoting a person to volunteer requires trusting that their government ID is genuine and that they are not an obvious high-risk individual. Today that trust is intended to be established manually; at global scale this is slow, inconsistent, and costly.

**Important split.** “Trust” is two capabilities:

1. **Document + presence** — prove the ID is real and the person is present (document authenticity, selfie / liveness, face match).
2. **Screening** — check sanctions / PEP / watchlists (and, where legally available, criminal-record sources). This is usually a **separate** product from document verification, with country-specific legal limits.

No shortlisted vendor is a full substitute for a country-by-country criminal-background bureau. Several offer **AML / watchlist / PEP / adverse-media** screening; that is what this document treats as the practical Phase-1 “screening” capability.

**Recommendation.** Prefer **Didit** as the primary Phase-1 provider for **both** document+liveness **and** AML screening, because it publishes modular pricing, covers 220+ countries for documents, exposes APIs suitable for AWS Lambda, and can combine ID verification + passive liveness + face match + AML in one workflow.

- **Estimated variable cost (list prices, USD, checked 2026-11-23):** about **$0.53** per successful full check (ID $0.15 + passive liveness $0.10 + face match $0.05 + AML $0.20), before plan discounts / free monthly credit. At 100 / 500 / 1,000 full checks: roughly **$53 / $265 / $530** variable (plus any Growth/Scale plan fees if used).
- **Runner-up combination:** **Stripe Identity** (document + selfie; Saayam already has a Stripe account) **plus** Didit AML ($0.20) or Persona Watchlist (plan-dependent). Stronger billing fit with Stripe; higher IDV unit cost (~$1.50) and screening still needs a second vendor.
- **Main risks.** Screening ≠ court criminal records; biometric and ID data are highly sensitive (GDPR / consent); some countries restrict background checks; vendor prices change.
- **Decision needed from leadership.** Approve Didit as Phase-1 primary (or the Stripe + screening combination), authorize a sandbox pilot (no real IDs), and clarify whether Phase-1 screening means AML/watchlist only or a true criminal-record product in specific countries.

---

## 2. Business context and problem statement

Saayam matches help-seekers with volunteers worldwide. Volunteer status confers trust and access. Accepting forged IDs, or promoting people with known high-risk flags that a reasonable screening would have caught, creates safety, legal, and reputational exposure.

**Today (as described for this analysis).** Phase 1 identity verification for volunteer promotion is expected to be **manual**, with the longer-term intent to delegate verification work to an external company. Volunteers upload diverse government documents (passport, driver’s license, and similar) from many countries.

**Cost of doing nothing.** Manual review does not scale: turnaround stretches as volume grows; quality varies by reviewer; forged IDs and presentation attacks are hard to catch without specialist tooling; leadership lacks a priced, auditable vendor path for donors and partners who ask how volunteers are vetted.

---

## 3. Objectives and success criteria

| Objective | Proposed target | Why this target |
|---|---|---|
| Turnaround | ≥ 90% of automated decisions within **15 minutes** of completed capture | Keeps volunteer onboarding interactive; flags only edge cases for humans |
| Cost per verified volunteer | **≤ $1.00** all-in variable cost for document + liveness + one screening check at ≤ 500 checks/month | Below rough manual cost (~$6–$8 if 15–20 minutes of staff time at ~$25/hour — **judgment**) |
| Geographic coverage | Document types covering **≥ 90%** of countries represented in the current volunteer applicant set within 90 days of go-live | Matches Saayam’s multi-country volunteer base |
| Integrity | Document authenticity + liveness (or enforced live capture) on **100%** of automated promotions | Addresses preferred “person is present” need |
| Screening | AML / sanctions / PEP / adverse-media (or agreed equivalent) on **100%** of promotions in Phase 1 | Practical stand-in until country-specific criminal APIs are scoped |
| Ops load | Manual review queue **≤ 10%** of sessions after the first month | Vendor automation should clear most clean cases |

Success is measured in a **pilot** (see §16): completion rate, false-reject / false-accept samples on synthetic/test fixtures only, median decision time, and $ per completed verification.

---

## 4. Scope

### In scope (this BRD / Phase 1 decision)

- Government **document authenticity** checks (passport, national ID, driver’s license as supported by the vendor).
- **Liveness / live capture** and face match to the document photo (preferred).
- **AML / watchlist / PEP / adverse-media** screening capability evaluation.
- Vendor shortlist, scoring, cost model, integration fit to Saayam’s stack, compliance notes, recommendation.

### Out of scope

- Building the production integration (Lambda, API Gateway, front end, mobile).
- Defining volunteer promotion business rules beyond “verification must pass.”
- Creating vendor accounts in Saayam’s name or contacting sales on Saayam’s behalf (maintainer approval required first).
- Uploading real ID documents or personal data to any vendor demo.
- Country-by-country court criminal-record bureau integrations (flagged as a later phase where legally available).

---

## 5. Stakeholders and users

| Stakeholder | What they need |
|---|---|
| **Volunteer applicants** | Clear consent, mobile-friendly capture, few retries, privacy explanation, predictable timing |
| **Reviewers / admins** | Dashboard or webhook results, reason codes, ability to override / escalate, audit trail |
| **Leadership** | Low cost, broad coverage, defensible trust story, clear risks and a decide-now recommendation |
| **Engineering** | REST API + webhooks, sandbox, Python-friendly, fits AWS Lambda + API Gateway + Postgres; works with React web and React Native mobile |

**Stack confirmation (repo facts, not vendor claims):**

- Web: React (`saayam-for-all/webapp` — “Contains only the web related React code”).
- Mobile: React Native (`saayam-for-all/mobileapp` exists).
- Backend pattern for this org: AWS Lambda behind API Gateway, Python, Postgres (Virginia analytics / data paths in this monorepo).
- Payments: leadership states Saayam already has a **Stripe** account.

---

## 6. Current process and target process

### Current (manual Phase 1 intent)

1. Applicant uploads an ID image (and possibly a selfie) in the app.
2. A human reviewer inspects authenticity and consistency.
3. Reviewer records an approve / reject decision.
4. Volunteer promotion proceeds or is blocked.

Gaps: no consistent liveness, weak forgery detection, no systematic watchlist check, slow at volume.

### Target process

```text
Volunteer starts promotion
        │
        ▼
Consent + privacy notice (purpose, retention, processors)
        │
        ▼
Vendor-hosted or embedded capture
  • Government ID (live camera preferred)
  • Selfie / liveness
        │
        ▼
Vendor: document authenticity + face match + liveness
        │
        ├── fail / needs_review ──► Admin queue ──► decision
        │
        ▼ pass
Screening step (same vendor or second vendor)
  • Sanctions / PEP / watchlist / adverse media
        │
        ├── hit / needs_review ──► Admin queue ──► decision
        │
        ▼ clear
Webhook → API Gateway → Lambda → Postgres
        │
        ▼
Volunteer eligible for promotion (per separate promotion rules)
```

---

## 7. Business requirements

Priorities: **Must** / **Should** / **Could**. Items marked **(proposed)** were added beyond the five starting needs.

| ID | Requirement | Priority | Rationale | Acceptance criterion |
|---|---|---|---|---|
| BR-01 | Verify government ID document authenticity (not obviously forged / tampered) | Must | Core trust need | Vendor returns a documented authenticity / document result; failed authenticity blocks auto-promotion |
| BR-02 | Confirm the person is present via live capture and/or liveness, with face match to the ID photo | Must | Preferred anti-spoof control | Session requires selfie/liveness; face-match result stored with the session |
| BR-03 | Support volunteers across many countries and common document types (passport, DL, national ID) | Must | Global volunteer base | Shortlisted vendor publishes ≥100 countries of document coverage (or equivalent public claim with source) |
| BR-04 | Keep variable cost as low as practical at 100–1,000 checks/month | Must | NGO cost sensitivity | Public list model allows estimating monthly cost; target ≤ $1 variable for full IDV+liveness+one screen at mid volume |
| BR-05 | Programmatic integration (API / SDK + webhooks) usable from Python on AWS Lambda behind API Gateway, with results stored in Postgres; usable from React web and React Native mobile | Must | Platform fit | Vendor documents REST API or server SDK, webhook callbacks, and a sandbox/test mode |
| BR-06 | Prefer reuse of existing Stripe commercial relationship where it does not violate BR-01–BR-05 | Should | Operational simplicity | If Stripe Identity is not primary, document why; if it is, screening gap must be closed by a second service |
| BR-07 | AML / sanctions / PEP / watchlist (or adverse-media) screening available for Phase 1 | Must **(proposed)** | Separates “document trust” from “person risk”; criminal-court APIs are rarely global | Provider marks clear / hit / needs_review; results auditable |
| BR-08 | Explicit end-user consent and data-minimization controls | Must **(proposed)** | Biometric + ID images are sensitive personal data | Consent captured before capture; retention/deletion policy documented |
| BR-09 | Sandbox or test environment that never requires real IDs for engineering pilots | Must **(proposed)** | Safety and policy compliance | Team can run end-to-end test sessions with vendor test fixtures only |
| BR-10 | Admin review path for borderline cases | Should **(proposed)** | Automation will not clear 100% | `needs_review` (or equivalent) routes to human decision without losing session data |
| BR-11 | Optional NFC / chip read for e-passports | Could **(proposed)** | Higher assurance where devices support it | Documented as optional enhancement, not Phase-1 blocker |

---

## 8. Market overview and shortlist

**How providers were found.** Starting from the issue-mandated names (Stripe Identity, Didit, ID.me), plus common KYC/IDV vendors with public docs useful to an NGO stack (Persona, Veriff, Onfido/Entrust). Sources: vendor marketing/docs/pricing pages and official developer docs. **No sales calls were made; no Saayam accounts were created.**

**Shortlist (6):**

1. Stripe Identity  
2. Didit  
3. ID.me  
4. Persona  
5. Veriff  
6. Onfido (Entrust Identity Verification)

---

## 9. Vendor evaluation

### 9.1 Coverage matrix (capabilities)

Legend: **Yes** = publicly documented; **Partial** = limited geography or add-on / plan-gated; **No** = not offered or not found in public docs; **Sales** = only via sales.

| Capability | Stripe Identity | Didit | ID.me | Persona | Veriff | Onfido / Entrust |
|---|---|---|---|---|---|---|
| Document authenticity | Yes (≥100 countries) | Yes (220+ countries/territories) | Yes (document verification APIs) | Yes | Yes (230+ countries; 12,500+ docs) | Yes (195+ countries claimed) |
| Liveness / live capture + face match | Yes (selfie match; live capture) | Yes (passive/active liveness + face match) | Partial (document + telecom flows; confirm liveness packaging with sales) | Yes | Yes (iBeta-conformant liveness on self-serve plans) | Yes (motion/liveness; iBeta claims on product pages) |
| Criminal **court** records (global) | No | No (not as universal court CR) | No (not positioned as global CR) | No | No | No |
| AML / sanctions / PEP / watchlist | No (explicit gap in public Identity scope) | Yes (AML screening, 1,300+ lists) | Sales / unclear as standard IDV add-on from public pricing pages | Yes (Watchlist Report; 200+ lists) | Yes (AML screening product + webhook) | Yes (watchlist add-on on marketplace listing) |
| Public self-serve pricing | Yes | Yes | No (contact sales; AWS pilot listing exists) | Partial (Essential published; Growth custom) | Yes (self-serve plans) | No commercial list (UK G-Cloud public-sector band only) |
| Sandbox / test mode | Yes (Stripe test mode) | Yes (sandbox free quotas) | API docs imply partner setup | Yes | Yes (trial called out) | Trial options on G-Cloud text |

**Fact:** No single shortlisted vendor replaces a full multi-country criminal-record bureau. **Judgment:** treat AML/watchlist as Phase-1 screening; pursue true criminal-record APIs later per country with legal review.

### 9.2 Weights (proposed) and scores

| Criterion | Weight | Justification |
|---|---|---|
| Document authenticity + liveness quality / fit | 0.30 | Primary trust control for uploaded IDs |
| Screening (AML/watchlist) availability | 0.20 | Second half of “trust”; cannot ignore |
| Cost transparency + estimated $/check | 0.20 | NGO constraint |
| Country / document coverage | 0.15 | Global volunteers |
| Integration fit (API, webhooks, Lambda, web+mobile, Stripe synergy) | 0.15 | Delivery risk |

Scoring: 1–5 per criterion (**judgment** informed by public docs). Total = Σ(weight × score).

| Provider | Doc+liveness | Screening | Cost | Coverage | Integration | **Total** |
|---|---:|---:|---:|---:|---:|---:|
| **Didit** | 5 | 5 | 5 | 5 | 4 | **4.85** |
| **Veriff** | 5 | 4 | 4 | 5 | 4 | **4.45** |
| **Onfido / Entrust** | 5 | 4 | 2 | 5 | 3 | **3.90** |
| **Persona** | 4 | 5 | 3 | 4 | 3 | **3.85** |
| **Stripe Identity** | 5 | 1 | 4 | 4 | 5 | **3.85** |
| **ID.me** | 3 | 2 | 1 | 3 | 3 | **2.40** |

Notes on integration scores: Stripe scores 5 for existing account + mature API; Persona loses points because **API-only** flows are called out as Enterprise in public docs; ID.me loses on opaque pricing and sales-led access.

### 9.3 Short profiles

**Stripe Identity — strengths:** Published $1.50 document+selfie pricing; first 50 verifications free; already aligned with Saayam’s Stripe account; Verification Sessions API + webhooks; strong docs. **Limits:** No AML/watchlist in Identity; ID-number lookup is US-SSN oriented; business availability has geographic constraints called out in third-party reviews of Stripe’s own pages. **Surprise:** Excellent fit for *half* of the problem only.

**Didit — strengths:** Modular public price list; full ID+liveness+face match ~$0.33 list for a common KYC set; AML $0.20; 220+ countries for ID verification; sandbox credits; workflow builder. **Limits:** Newer brand vs Stripe/Onfido; plan discounts and credit model need finance to model carefully after Nov 2026 pricing change. **Surprise:** One vendor can cover both trust halves at the lowest public combined rate in this shortlist.

**ID.me — strengths:** Strong US public-sector / consumer credential brand; Services API for document verification; FedRAMP-oriented marketplace presence. **Limits:** No public per-check business price (contact sales); AWS Marketplace pilot listed at **$50,000 / 12 months** (private offer) — likely heavy for early NGO volume. **Surprise:** Consumer-free verification does not mean free for Saayam as the relying party.

**Persona — strengths:** Watchlist reports (200+ lists); inquiries + webhooks; Essential plan published ($250/mo annual, 500 services then $1.50). **Limits:** API-only integration restricted to Enterprise per docs; Growth pricing is sales-led. **Surprise:** Easy to underestimate TCO once volume exceeds the 500 included services.

**Veriff — strengths:** 230+ countries; published self-serve plans from $0.80 (with monthly minimums); liveness included on plans; AML screening + dedicated webhook. **Limits:** Monthly minimums ($49–$209) hurt very low volume; AML packaging/pricing beyond IDV needs confirmation on the plan page / docs. **Surprise:** “Pay for decisions not retries” is favorable if capture UX causes retries.

**Onfido / Entrust — strengths:** Broad document library; mature SDKs; watchlist add-on; iBeta liveness claims. **Limits:** Commercial pricing is quote-only; G-Cloud bands are public-sector oriented. **Surprise:** Strong product, weak price transparency for an NGO first purchase.

---

## 10. Cost analysis

All figures **USD list** unless noted. **Checked 2026-11-23** unless a source date is stated. Mark **contact sales** where public prices are missing.

### 10.1 Pricing models (facts)

| Provider | Model (public) | Unit price signals | Free / minimum |
|---|---|---|---|
| Stripe Identity | Per completed verification | $1.50 document+selfie; $0.50 US SSN lookup | First 50 verifications free; custom if >2,000/mo |
| Didit | Per completed feature / credits | ID $0.15; passive liveness $0.10 (workflow) / $0.05 (standalone); face match $0.05; AML $0.20; full ID+liveness+face+IP example $0.33 | $10 free credit/month (new pricing from 2026-11-01); sandbox quotas |
| ID.me | **Contact sales** | No public per-check rate in docs; AWS Marketplace pilot **$50,000 / year** private offer | Consumer side free; relying party pays |
| Persona Essential | Subscription + overage | $250/mo (annual) includes 500 services; then $1.50/service | 500/mo included (no rollover) |
| Veriff Self-Serve | Per verification + monthly minimum | Essential $0.80 (min $49); Plus $1.39 (min $99); Premium $1.89 (min $209) | Free Premium trial (marketing page) |
| Onfido / Entrust | **Contact sales** | UK G-Cloud band £0.43–£2.12 / transaction (public sector) | Trial options mentioned on marketplace text |

### 10.2 Estimated monthly variable cost — full trust path

**Assumption for “full check” (judgment):** one document verification + liveness/selfie + one AML/watchlist screen where the vendor offers it.

| Volume | Didit (ID+pass. live+face+AML ≈ $0.53) | Stripe IDV only ($1.50) | Stripe + Didit AML ($1.70) | Veriff Essential IDV only ($0.80 + enforce $49 min) | Persona Essential (sub + overage; watchlist counts as service) |
|---|---:|---:|---:|---:|---:|
| 100 | ~$53 | $150 (after free 50 → ~$75 first month if free applies) | ~$170 | max($49, $80) → **$80** | $250 (within 500) |
| 500 | ~$265 | $750 | ~$850 | max($49, $400) → **$400** | $250 (exactly at included 500 if only one service each) |
| 1,000 | ~$530 | $1,500 | ~$1,700 | **$800** | $250 + 500×$1.50 = **$1,000** |

**Hidden / easy-to-miss costs:** failed sessions that still bill; manual review labor; webhook infra; storing images in S3; legal review; plan minimums (Veriff); unused subscription capacity (Persona); FX taxes; rechecks; ongoing AML monitoring fees (Didit $0.07/user/year if enabled).

### 10.3 Manual baseline (judgment)

If a staff reviewer spends 15–20 minutes per applicant at a fully loaded ~$25/hour, manual cost is about **$6–$8 per person**, before forgery-tooling quality. Automated Phase-1 at Didit list rates is roughly **an order of magnitude cheaper** at 100–1,000/month, even after adding admin time for the review queue.

---

## 11. Integration and technical fit

Target pattern: **Volunteer app (React / React Native) → vendor capture (hosted or SDK) → vendor webhooks → API Gateway → Python Lambda → Postgres**. Optional: Lambda creates the vendor session with secret keys from SSM/Secrets Manager (never in the repo).

| Provider | Capture style | API / SDK | Webhooks | Sandbox | Stripe account synergy | Effort |
|---|---|---|---|---|---|---|
| Stripe Identity | Stripe-hosted Verification Session / mobile support via Stripe docs | Stripe API (Python SDK exists ecosystem-wide) | Yes | Test mode | **Native** | **Low** — already on Stripe |
| Didit | Workflow links + standalone APIs | REST (`x-api-key`), modular features | Yes (`status.updated` etc.) | Free sandbox quotas | None required | **Low–Medium** — new vendor, clear REST |
| ID.me | Partner flows + Services API | REST (account-manager API key) | Callback URL parameters in API errors/docs | Partner-provisioned | None | **High** — sales access + opaque packaging |
| Persona | Hosted / embedded inquiries; mobile SDKs | REST; **API-only = Enterprise** | Yes | Yes | None | **Medium–High** depending on plan |
| Veriff | Hosted page or API media upload | REST + Client SDKs | Decision + AML webhooks | Trial / test | None | **Medium** |
| Onfido / Entrust | SDKs + workflows | API/SDK | Yes (product dependent) | Trial options | None | **Medium–High** (sales + enterprise motion) |

---

## 12. Compliance, privacy and legal considerations

**Facts / general constraints (not legal advice):**

- Government ID images and biometrics are sensitive personal data. Under **GDPR** (EU/EEA volunteers) and similar regimes, Saayam needs a lawful basis, clear **consent**, purpose limitation, retention limits, processor agreements (DPAs), and cross-border transfer mechanisms if vendors process outside the volunteer’s region.
- **Criminal-record** checks are heavily regulated. Many countries restrict who may request court records, for what purpose, and with what notice. A US-centric “background check” product often **cannot** be applied globally.
- **AML/sanctions/PEP** screening is widely used in KYC and is the practical Phase-1 screen; it is **not** the same as a local police certificate.
- Stripe Identity public materials emphasize consent and data minimization; customers remain responsible for biometric-law compliance in some jurisdictions (called out in independent reviews of Stripe’s positioning).
- Do not store raw ID images longer than needed; prefer vendor-hosted evidence with retention controls where acceptable.

**Countries / cases where criminal checks are unavailable or restricted (illustrative, not exhaustive):** jurisdictions that require individual-initiated police certificates; places where employer/NGO access to criminal databases is illegal without specific licenses; minors (several vendors prohibit verifying under a minimum age — Stripe Identity public review notes under-16 restrictions).

**Judgment:** Leadership should have counsel review the chosen vendor’s DPA and biometric terms before production, especially for EU volunteers and for any later true criminal-record expansion.

---

## 13. Risks, assumptions, dependencies, and constraints

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Treating AML hits as “criminal history” | Medium | High (wrong decisions / legal exposure) | Name Phase-1 capability accurately; counsel review; human review on hits |
| Vendor price / packaging change | High | Medium | Re-check sources before contract; prefer published list + pilot |
| False rejects block good volunteers | Medium | Medium | Tune thresholds; BR-10 admin path; monitor completion rate |
| False accepts (forged ID / deepfake) | Low–Medium | High | Require liveness; sample audit; prefer vendors with published PAD/liveness testing |
| Biometric consent failure | Medium | High | Consent UX before camera; store consent record in Postgres |
| Dual-vendor complexity (Stripe + screener) | Medium | Medium | Prefer single-vendor Didit for Phase 1 unless Stripe relationship is mandatory |
| No AWS / sales account yet | High (process) | Low | Maintainer creates sandbox; engineers use test fixtures only |
| Mobile camera quirks | Medium | Medium | Test on React Native early; prefer vendor mobile SDKs or well-tested hosted flows |

**Assumptions:** Volunteer promotion volume stays near 100–1,000 verifications/month in Year 1; English-first UX is acceptable initially; Phase 1 screening = AML/watchlist, not global court CR.

**Dependencies:** Maintainer approval before any Saayam-named vendor account; Secrets Manager/SSM for API keys; webhook HTTPS endpoint; legal DPA.

**Constraints:** Docs-only deliverable for #694; no real IDs in demos; no credentials in git; PR against `test`.

---

## 14. Recommendation

**Primary recommendation: Didit** for Phase-1 document authenticity, liveness/face match, **and** AML/watchlist screening.

**Why (judgment grounded in facts above):** highest weighted score; public modular pricing that meets the cost objective; broad document coverage; AML available in the same platform; REST + webhooks fit Lambda; sandbox available without uploading real IDs.

**Runner-up: Stripe Identity + Didit AML (or Persona Watchlist on a suitable plan).** Choose this if leadership prioritizes keeping identity capture on the existing Stripe account and accepts higher IDV unit cost plus a second integration.

**Choose differently when:**

- Leadership mandates a single US-government-oriented credential network → re-open **ID.me** after a maintainer-approved sales conversation (pricing opaque today).
- Volume is tiny (<50/month) and Stripe free tier matters → start with **Stripe Identity** alone for document+selfie, add screening before scaling promotions.
- Enterprise procurement prefers Entrust/Onfido brand and will run an RFP → use Onfido as RFP anchor, not as self-serve default.

---

## 15. Proposed next steps

1. Leadership accepts primary (Didit) or runner-up (Stripe + screener).  
2. Maintainer creates a **sandbox-only** vendor account (not by individual contributors contacting sales in Saayam’s name).  
3. Engineering spike (1–2 weeks): create session → test webhook → persist result schema in Postgres; **test fixtures only**.  
4. Pilot with a small internal volunteer cohort using **synthetic / vendor test identities**, never production stranger IDs in sandbox misuse.  
5. Measure: median time, pass/fail/review rates, $ per completed full check, mobile completion rate.  
6. Go/no-go for production; then schedule legal DPA + retention policy sign-off.  
7. Later phase: country-specific criminal-record options where lawful.

---

## 16. Open questions (for leadership)

1. Is Phase-1 “no criminal history” satisfied by **AML/sanctions/PEP/adverse-media**, or must specific countries require official police certificates?  
2. Is staying on **Stripe** for capture mandatory, or is cost/coverage allowed to win?  
3. What is the expected monthly verification volume for the next 12 months?  
4. How long may ID images / biometrics be retained, and where (vendor vs Saayam S3)?  
5. Who is the human reviewer of record for `needs_review` queues?  
6. Are there countries Saayam will **not** onboard volunteers from regardless of vendor coverage?  
7. May engineering use vendor sandboxes under a maintainer-owned account this quarter?

---

## 17. Appendix A — Sources (link + date checked)

| # | Source | URL | Checked |
|---|---|---|---|
| S1 | Stripe Identity product | https://stripe.com/identity | 2026-11-23 |
| S2 | Stripe pricing (Identity section) | https://stripe.com/pricing | 2026-11-23 |
| S3 | Stripe Identity docs hub | https://docs.stripe.com/identity | 2026-11-23 |
| S4 | Didit pricing docs | https://docs.didit.me/getting-started/pricing | 2026-11-23 |
| S5 | Didit AML product page | https://didit.me/products/aml-screening/ | 2026-11-23 |
| S6 | Didit liveness overview | https://docs.didit.me/core-technology/liveness/overview | 2026-11-23 |
| S7 | Didit pricing change note (1 Nov 2026) | https://didit.me/blog/new-pricing-november-2026/ | 2026-11-23 |
| S8 | ID.me Services API overview | https://docs.id.me/apis/services-api/overview | 2026-11-23 |
| S9 | ID.me APIs overview | https://docs.id.me/apis/overview | 2026-11-23 |
| S10 | ID.me AWS Marketplace private-offer listing | https://aws.amazon.com/marketplace/pp/prodview-35b2ffl56ywso | 2026-11-23 |
| S11 | Persona plans overview | https://help.withpersona.com/articles/6oZbzp7jb7AWGClF5vpY3K/ | 2026-11-23 |
| S12 | Persona Watchlist Report | https://help.withpersona.com/articles/UQGaDEhkQ7TLAMJsjuXiX/ | 2026-11-23 |
| S13 | Persona API introduction (API-only = Enterprise note) | https://docs.withpersona.com/api-introduction | 2026-11-23 |
| S14 | Persona pricing site | https://withpersona.com/pricing/ | 2026-11-23 |
| S15 | Veriff pricing | https://www.veriff.com/pricing | 2026-11-23 |
| S16 | Veriff country coverage | https://www.veriff.com/supported-countries | 2026-11-23 |
| S17 | Veriff webhooks guide (incl. AML webhook) | https://devdocs.veriff.com/docs/webhooks-guide | 2026-11-23 |
| S18 | Onfido / Entrust UK G-Cloud service listing | https://www.applytosupply.digitalmarketplace.service.gov.uk/g-cloud/services/168785180660845 | 2026-11-23 |
| S19 | Saayam webapp repo description (React) | https://github.com/saayam-for-all/webapp | 2026-11-23 |
| S20 | Saayam mobileapp repo (React Native) | https://github.com/saayam-for-all/mobileapp | 2026-11-23 |
| S21 | Issue #694 requirements | https://github.com/saayam-for-all/data/issues/694 | 2026-11-23 |

Independent reviews (used only as secondary context, not as pricing authority): Stripe Identity review pages summarizing public Stripe limits (e.g. startwithidentity.com, checked via search 2026-11-23).

---

## 18. Appendix B — Glossary

| Term | Meaning |
|---|---|
| **AML** | Anti–money laundering screening (sanctions, often PEP and adverse media) |
| **BRD** | Business requirements document |
| **Face match** | Comparing a live selfie to the portrait on an ID |
| **Liveness / PAD** | Checks that a real person is present (not a photo/replay/deepfake); presentation-attack detection |
| **PEP** | Politically exposed person |
| **Watchlist** | Sanctions / warning lists used in screening |
| **Verification session** | One vendor-managed attempt to verify a person |
| **Webhook** | HTTP callback from vendor to Saayam when a session/report updates |

---

### Document quality checklist (self-review)

- [x] Document control present  
- [x] Executive summary stands alone  
- [x] Business context, objectives, scope, stakeholders  
- [x] Current vs target process  
- [x] Numbered BRs with priority, rationale, acceptance criteria  
- [x] ≥5 providers including Stripe Identity, Didit, ID.me  
- [x] Each provider marked for document authenticity, liveness, and screening  
- [x] Weighted scores with explained weights  
- [x] Costs with sources/dates; “contact sales” marked  
- [x] Integration fit per provider  
- [x] Compliance / legal limits discussed  
- [x] Recommendation + runner-up  
- [x] Next steps + open questions  
- [x] Appendix sources + glossary  
