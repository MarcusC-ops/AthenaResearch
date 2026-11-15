# Coordinator Dashboard - Quick Start

## Login
- URL: http://localhost:8000/panel/
- Use the coordinator account configured by your local `seed_demo` setup.

## Pages

### Dashboard (/panel/)
- **4 metric tiles**: Active studies, New applications (high priority), Screenings this week, Payouts awaiting
- **2 tables**: Applications awaiting review, Screenings in next 7 days
- Shows only data for coordinator's organisation

### Participation (/panel/participation/)
- List of enrolled and completed participants
- Filter by study
- Shows: Participant name, Study, Status, Visits attended/total, Paid so far, Due now
- Click participant name to open detail page

### Participation Detail (/panel/participation/<id>/)
- **Screening card**: Date, time, site, status
- **Compensation card**: Amount due now, "Request payout" button (active if > $0)
- **Visits table**:
  - If status is PROPOSED/CONFIRMED: inline date picker + "Save date" button
  - If date is past: "Attended" and "Missed" buttons
  - Shows status badge
- **Payouts table**: Amount, status, paid date, reference, rejection reason
- **Action buttons**: "Mark as completed" (if not completed), "Withdraw participant"

### Participation Withdraw (/panel/participation/<id>/withdraw/)
- Confirmation page
- Optional reason field
- Confirm or cancel

### Insights (/panel/insights/)
- Filter by study
- **Recruitment funnel**: Applied → Pre-screen → Shortlist → Screened → Passed → Enrolled → Completed (with CSS bars)
- **Screening pass rates**: By ML-2 band (high, medium, low, unscored)
- **Band distribution**: Count by band
- **Demographics** (age band, sex, region):
  - Applied vs Enrolled columns
  - "fewer than 5" for groups 1-4
  - Only counts participants who agreed to insights sharing

## Key Features

### Visit Dating & Marking
1. On Participation Detail, click "Save date" on unscheduled visit
2. Pick date/time in datetime picker
3. Once date is in the past, "Attended" and "Missed" buttons appear
4. Only ATTENDED visits count toward compensation

### Payout Requests
1. When at least one visit is attended, "Amount due" > 0 in compensation card
2. Click "Request payout" button
3. System creates REQUESTED payout
4. Coordinator can request multiple times as more visits are attended

### Payouts Status
- **REQUESTED**: Waiting for Athena staff to pay
- **PAID**: Completed, shows reference and paid date

### Completing Participation
1. Mark all visits attended/missed
2. Request any final payout
3. Click "Mark as completed"
4. Application status changes to COMPLETED
5. Participant can no longer be updated

## Business Logic

**Earned Amount** = Study compensation × (Attended visits / Total visits)
- Rounded using banker's rounding (ROUND_HALF_UP)

**Amount Due** = Earned - Already Paid - Already Requested
- Never goes negative
- Once all earned amount is paid, button disappears

**Dashboard Metrics**
- **High priority**: HIGH band applications in UNDER_REVIEW status
- **Awaiting review**: Total in UNDER_REVIEW status
- **Screenings this week**: SCREENING appointments in next 7 days, PROPOSED or CONFIRMED status

## Technical Details

### Database
- Uses existing Appointment model for visit scheduling
- Uses existing Payout model for compensation tracking
- No new models or migrations

### Permissions
- View restricted to users with `core.panel_access` permission
- Data scoped to coordinator's organisation via `staff_profile.organisation`

### Template Filters
- `suppress_small`: Shows 0/"0", 1-4/"fewer than 5", 5+/number
- `get_item`: Dictionary key lookup for age band/region names

## Troubleshooting

**"Access denied" message?**
- Ensure logged-in user has coordinator role and belongs to an organisation

**Visits not appearing?**
- Participant must be in ENROLLED status
- Visit appointments must exist (created during enrolment)

**"Attended" and "Missed" buttons not showing?**
- Visit scheduled_for must be ≤ current date/time
- Status must be PROPOSED or CONFIRMED

**Demographics showing "—" or fewer than 5?**
- Participant must have `consent_insights = True`
- Groups of 1-4 automatically suppressed per business rules (BR-16)

**Payout request button not active?**
- Amount due must be > 0
- Check earned calculation and existing paid/requested amounts
