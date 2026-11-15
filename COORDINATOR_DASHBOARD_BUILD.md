# Coordinator Dashboard Increment - Build Summary

## Overview
Completed the coordinator dashboard increment for Athena. Coordinators can now:
1. Track participant visit attendance and dates
2. Calculate and request compensation payouts
3. View recruitment insights (funnel, screening rates, demographics)
4. See a real-time dashboard of what needs attention today

## Architecture

### Services (core/services.py)
13 new functions added:

**Visit & Payout Management:**
- `save_visit_date(appointment, scheduled_for, user)` - Set visit date, reset to PROPOSED
- `mark_visit(appointment, attended, user)` - Mark as attended/missed (requires scheduled_for ≤ now)
- `earned_amount(application)` - Calculate earned pay: compensation × attended_visits/total_visits
- `amount_due(application)` - Calculate due pay: earned - paid - requested (≥ 0)
- `request_payout(application, user)` - Create requested payout
- `complete_participation(application, user)` - Mark application as COMPLETED
- `coordinator_withdraw(application, user, reason)` - Withdraw participant

**Insights:**
- `study_funnel(qs)` - Recruitment funnel (applied, pre-screen, shortlist, screened, passed, enrolled, completed)
- `band_pass_rates(qs)` - Screening pass rates by ML-2 band
- `band_distribution(qs)` - Application counts by ML-2 band
- `applicant_mix(qs)` - Demographics (age, sex, region) for applied vs enrolled with insights consent
- `coordinator_dashboard(user)` - Dashboard metrics: studies, high-priority apps, screening appointments, payouts

### Forms (adminpanel/forms.py)
- `VisitDateForm` - DateTime input for scheduling visit
- `ParticipationFilterForm` - Study filter for participation list
- `CoordinatorWithdrawForm` - Withdrawal reason textarea

### Views (adminpanel/views.py)
All decorated with `@coordinator_required`:
- `participation()` - List enrolled/completed participants with visit counts and amount due
- `participation_detail()` - Edit visit dates, mark attended/missed, request payouts, complete study
- `participation_withdraw()` - Confirmation page for participant withdrawal
- `insights()` - Recruitment funnel, pass rates, band distribution, demographics

### Templates (templates/adminpanel/)
- `dashboard_coordinator.html` - 4 metric tiles + 2 tables (applications awaiting review, screenings this week)
- `participation.html` - Filterable table of enrolled/completed participants
- `participation_detail.html` - Visit tracking with inline date/status editing, payout card, withdrawal button
- `participation_withdraw.html` - Confirmation page with reason field
- `insights.html` - Recruitment funnel with CSS bars (no chart library), pass rates, band distribution, demographics

### Template Filters (core/templatetags/athena_filters.py)
- `suppress_small` - Shows "fewer than 5" for 1-4, "0" for zero, number for 5+
- `get_item` - Dictionary access helper for demographics tables

### Database
No new models or migrations needed. Uses existing fields:
- `Appointment.scheduled_for` - Visit date/time
- `Appointment.status` - ATTENDED/MISSED (existing choices)
- `Payout` model (existing) with REQUESTED/PAID statuses
- `Application.status` - ENROLLED/COMPLETED

### Seed Data
Updated `core/management/commands/seed_demo.py`:
- Aisyah Rahman: 1 paid payout (S$140) + 1 requested (S$70)
- Memory Games study: 2 paid payouts (S$30 each) + 1 requested (S$30)

## Key Implementation Details

**Payout Logic:**
- `earned_amount()` multiplies study compensation by attended_visits/total_visits, rounded ROUND_HALF_UP
- `amount_due()` subtracts paid + requested from earned, never goes below 0
- Requested payouts have `reference=None` (no reference until paid)

**Visit Workflow:**
- Coordinator sets `scheduled_for` → appointment stays PROPOSED
- Once scheduled_for ≤ now(), coordinator can mark as ATTENDED or MISSED
- Only ATTENDED visits count toward compensation

**Insights Consent:**
- Demographics only count participants with `participant.consent_insights=True`
- Groups of 1-4 show "fewer than 5", 0 shows "0", 5+ show number

**Dashboard Scoping:**
- Coordinator dashboard filters all data by `user.staff_profile.organisation`
- Shows active (PUBLISHED/PAUSED/FULL) studies only
- Highlights high-priority (HIGH band) applications awaiting review
- Lists screenings in next 7 days

**Funnel Counting:**
- Uses `distinct()` to count applications that "ever reached" each status
- Not current status, so applicants who pass then are marked incomplete still count in "passed"

## Testing & Verification

✓ Django system checks pass (no issues)
✓ seed_demo creates 5 payouts and runs idempotently
✓ Coordinator user has correct permissions and staff_profile
✓ All service functions return expected data types
✓ Payout calculations verified (Aisyah: 3/5 attended → S$210 earned, S$140 paid, S$70 requested, S$0 due)
✓ Dashboard metrics render correctly (8 awaiting review, 2 payouts awaiting, etc.)
✓ All URLs and templates wired correctly
✓ Sidebar shows Participation & Insights links for coordinators only

## Files Modified/Created

Created:
- core/templatetags/__init__.py
- core/templatetags/athena_filters.py
- templates/adminpanel/dashboard_coordinator.html
- templates/adminpanel/participation.html
- templates/adminpanel/participation_detail.html
- templates/adminpanel/participation_withdraw.html
- templates/adminpanel/insights.html

Modified:
- core/services.py (added 13 functions)
- adminpanel/forms.py (added 3 forms)
- adminpanel/views.py (updated dashboard view, added 4 new views)
- adminpanel/urls.py (added 4 routes)
- templates/adminpanel/base_panel.html (sidebar links)
- core/management/commands/seed_demo.py (payout creation)

## Increment Requirements Met

✓ Coordinators date each visit and mark Attended or Missed
✓ Only attended visits counted toward compensation (BR-13)
✓ Athena works out amount due: compensation × attended/total, minus paid/requested
✓ Coordinators request payouts
✓ Coordinators view participation list with amounts due
✓ Insights page shows recruitment funnel, pass rates, band distribution
✓ Demographics only include participants with insights consent (BR-17)
✓ Groups 1-4 shown as "fewer than 5", 0 as "0" (BR-16)
✓ Bars are plain HTML & CSS with no chart library
✓ Dashboard home page shows coordinator-specific tiles and tables

## House Rules Compliance

✓ Django 5.2 LTS on Python 3.12+, SQLite, server-rendered templates
✓ Bootstrap 5.3 + Inter font from CDN
✓ Only packages in requirements.txt
✓ No REST framework, React, htmx, crispy-forms, chart libraries
✓ All code in correct locations (models in core/models.py, services in core/services.py, etc.)
✓ All data changes via POST + {% csrf_token %} + redirect + messages
✓ Destructive actions (withdraw) go through confirmation page
✓ White pages, black type, accent blue (#1A12E0), flat cards with 1px borders
✓ British English throughout (organisation, enrol, centre)
✓ No Django admin installed
✓ URL paths and labels exactly as specified
✓ Earlier work preserved, no models deleted or rewritten
✓ No tests or commits in build step
