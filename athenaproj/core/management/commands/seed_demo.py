"""Create the realistic, repeatable Athena demonstration catalogue."""

import calendar
import os
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, User
from django.utils import timezone

from core.models import (
    Application,
    Condition,
    Organisation,
    PreScreenQuestion,
    Region,
    Site,
    Study,
    StudyCategory,
    ParticipantProfile,
    Shortlist,
    StaffProfile,
)
from core.validators import normalise_sg_mobile
from core.services import is_eligible, submit_application


def add_months(value, months):
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


class Command(BaseCommand):
    help = 'Create or update the Athena demonstration catalogue.'

    def handle(self, *args, **options):
        regions = self.create_regions()
        conditions = self.create_conditions()
        categories = self.create_categories()
        organisations = self.create_organisations()
        sites = self.create_sites(organisations, regions)
        studies = self.create_studies(organisations, categories, sites, regions, conditions)
        self.create_questions(studies)
        self.create_people(organisations, regions, conditions)
        self.create_full_study_applications(studies, regions, conditions)
        self.create_shortlists(studies)

        for label, model in (
            ('Regions', Region),
            ('Conditions', Condition),
            ('Categories', StudyCategory),
            ('Organisations', Organisation),
            ('Sites', Site),
            ('Studies', Study),
            ('Pre-screen questions', PreScreenQuestion),
        ):
            self.stdout.write(f'{label}: {model.objects.count()}')
        self.stdout.write(
            f"Demo password: {os.environ.get('ATHENA_DEMO_PASSWORD', 'AthenaDemo2026!')}"
        )

    def create_shortlists(self, studies):
        profile = ParticipantProfile.objects.get(user__username='aisyah@example.com')
        selected_studies = [
            studies[title] for title in (
            'A Good Night in the City',
            'Understanding Eczema in Humid Weather',
            'Stress, Rest and Resilience',
            )
        ]
        Shortlist.objects.filter(
            participant=profile,
        ).exclude(study__in=selected_studies).delete()
        for study in selected_studies:
            Shortlist.objects.get_or_create(
                participant=profile,
                study=study,
            )

    def create_people(self, organisations, regions, conditions):
        password = os.environ.get('ATHENA_DEMO_PASSWORD', 'AthenaDemo2026!')
        people = [
            ('Aisyah', 'Rahman', 'aisyah@example.com', 'Participant', None, '', '9123 4567', True),
            ('Tan Ah', 'Kow', 'mrtan@example.com', 'Participant', None, '', '8123 4567', True),
            ('Daniel', 'Lim', 'drlim@kentridge-crc.sg', 'Coordinator', organisations['Kent Ridge Clinical Research Centre'], 'Clinical research coordinator', '9123 4567', True),
            ('Priya', 'Nair', 'priya@athena.sg', 'Staff', None, 'Operations executive', '9123 4567', True),
            ('Wei Ling', 'Tan', 'admin@athena.sg', 'Admin', None, 'Platform admin', '9123 4567', True),
            ('Nurul', 'Huda', 'nurul@harbourfront.sg', 'Coordinator', organisations['Harbourfront General Hospital'], '', '9123 4567', False),
        ]
        for first_name, last_name, email, group_name, organisation, job_title, mobile, active in people:
            user, _ = User.objects.get_or_create(
                username=email,
                defaults={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'is_active': active,
                },
            )
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = active
            user.set_password(password)
            user.save()
            user.groups.set([Group.objects.get(name=group_name)])
            if group_name == 'Participant':
                profile_defaults = {
                    'mobile': normalise_sg_mobile(mobile),
                    'terms_accepted_at': user.date_joined,
                }
                if email == 'aisyah@example.com':
                    profile_defaults.update(
                        date_of_birth=timezone.localdate().replace(
                            year=timezone.localdate().year - 24
                        ),
                        sex='female',
                        region=regions['W'],
                        employment='student',
                        education='degree',
                        height_cm='160.0',
                        weight_kg='52.0',
                        smoker=False,
                        activity_level='high',
                        motivation='help_research',
                        availability='weekday_evenings',
                        max_travel_minutes='30',
                        consent_matching=True,
                        consent_insights=True,
                        consent_contact=True,
                        onboarding_completed_at=timezone.now(),
                    )
                else:
                    profile_defaults.update(
                        date_of_birth=timezone.localdate().replace(
                            year=timezone.localdate().year - 67
                        ),
                        sex='male',
                        region=regions['NE'],
                        employment='retired',
                        education='secondary',
                        height_cm='168.0',
                        weight_kg='74.0',
                        smoker=False,
                        activity_level='moderate',
                        motivation='health_check',
                        availability='weekday_daytime',
                        max_travel_minutes='30',
                        consent_matching=True,
                        consent_insights=False,
                        consent_contact=False,
                        onboarding_completed_at=timezone.now(),
                    )
                ParticipantProfile.objects.update_or_create(
                    user=user,
                    defaults=profile_defaults,
                )
                profile = ParticipantProfile.objects.get(user=user)
                if email == 'mrtan@example.com':
                    profile.conditions.set([
                        conditions['Hypertension'],
                        conditions['Type 2 diabetes'],
                    ])
                else:
                    profile.conditions.clear()
                from core.services import refresh_interest_predictions
                refresh_interest_predictions(profile)
            else:
                StaffProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        'organisation': organisation,
                        'job_title': job_title,
                        'mobile': normalise_sg_mobile(mobile),
                    },
                )

        demo_names = [
            ('Siti', 'Aminah'), ('Cheryl', 'Goh'), ('Arjun', 'Menon'),
            ('Marcus', 'Teo'), ('Nadia', 'Ismail'), ('Ethan', 'Wong'),
            ('Hui Min', 'Lee'), ('Ravi', 'Kumar'), ('Farah', 'Yusof'),
            ('Jon', 'Ng'), ('Mei Lin', 'Chua'), ('Dev', 'Raj'),
            ('Ivy', 'Ho'), ('Samir', 'Das'), ('Nur', 'Aziz'),
            ('Grace', 'Ong'), ('Kai', 'Tan'), ('Maya', 'Pillai'),
            ('Alicia', 'Lim'), ('Hafiz', 'Rahman'), ('Elaine', 'Koh'),
            ('Vikram', 'Sethi'), ('Samantha', 'Low'), ('Imran', 'Salleh'),
        ]
        for index, (first_name, last_name) in enumerate(demo_names, 1):
            email = f'demo{index:02d}@example.com'
            user, _ = User.objects.get_or_create(username=email)
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = True
            user.set_password(password)
            user.save()
            user.groups.set([Group.objects.get(name='Participant')])
            profile, _ = ParticipantProfile.objects.get_or_create(
                user=user,
                defaults={
                    'mobile': normalise_sg_mobile(f'8{index:07d}'),
                    'terms_accepted_at': user.date_joined or timezone.now(),
                },
            )
            profile.date_of_birth = timezone.localdate().replace(
                year=timezone.localdate().year - (21 + index % 45)
            )
            profile.sex = 'female' if index % 2 else 'male'
            profile.region = regions[list(regions)[index % len(regions)]]
            profile.employment = 'full_time'
            profile.education = 'degree'
            profile.height_cm = '165.0'
            profile.weight_kg = '68.0'
            profile.smoker = index % 7 == 0
            profile.activity_level = 'moderate'
            profile.motivation = 'help_research'
            profile.availability = 'flexible'
            profile.max_travel_minutes = '60'
            profile.consent_matching = index % 5 != 0
            profile.consent_insights = index % 3 != 0
            profile.consent_contact = True
            profile.onboarding_completed_at = profile.onboarding_completed_at or timezone.now()
            profile.save()
            if index % 4 == 0:
                profile.conditions.set([conditions['Hypertension']])
            elif index % 4 == 1:
                profile.conditions.set([conditions['Asthma']])
            else:
                profile.conditions.clear()
            from core.services import refresh_interest_predictions
            refresh_interest_predictions(profile)

    def create_full_study_applications(self, studies, regions, conditions):
        applicants = list(
            ParticipantProfile.objects.filter(user__username__startswith='demo')
            .order_by('id')
        )
        public_studies = [
            study for study in studies.values() if study.status in (Study.Status.PUBLISHED, Study.Status.FULL)
        ]
        added = 0
        for profile in applicants:
            for study in public_studies:
                if added >= 30:
                    return
                if Application.objects.filter(participant=profile, study=study).exists():
                    continue
                if not is_eligible(profile, study):
                    continue
                site = study.sites.first()
                if site is None:
                    continue
                questions = list(study.pre_screen_questions.all())
                answers = {
                    question.pk: question.preferred_answer or question.option_list()[0]
                    for question in questions
                }
                application, created = submit_application(
                    profile, study, answers, site.pk,
                    profile.availability or 'flexible', True,
                )
                if created:
                    added += 1

    def create_regions(self):
        values = [
            ('C', 'Central', 1),
            ('N', 'North', 2),
            ('NE', 'North-East', 3),
            ('E', 'East', 4),
            ('W', 'West', 5),
        ]
        return {
            code: Region.objects.update_or_create(
                code=code,
                defaults={'name': name, 'display_order': display_order},
            )[0]
            for code, name, display_order in values
        }

    def create_conditions(self):
        values = [
            ('Allergic rhinitis', 'respiratory'),
            ('Anxiety', 'mental'),
            ('Asthma', 'respiratory'),
            ('Chronic kidney disease', ''),
            ('COPD', 'respiratory'),
            ('Depression', 'mental'),
            ('Eczema', 'skin'),
            ('Endometriosis', ''),
            ('Fatty liver disease', ''),
            ('GERD', ''),
            ('High cholesterol', 'high_cholesterol'),
            ('Hypertension', 'hypertension'),
            ('Insomnia', 'sleep'),
            ('Migraine', ''),
            ('Obstructive sleep apnoea', 'sleep'),
            ('Osteoarthritis', ''),
            ('Polycystic ovary syndrome', ''),
            ('Prediabetes', 'diabetes'),
            ('Psoriasis', 'skin'),
            ('Type 2 diabetes', 'diabetes'),
        ]
        return {
            name: Condition.objects.update_or_create(
                name=name,
                defaults={'slug': name.lower().replace(' ', '-'), 'ml_flag': ml_flag},
            )[0]
            for name, ml_flag in values
        }

    def create_categories(self):
        values = [
            ('Cognitive', 'cognitive', 'cognitive'),
            ('Healthy Volunteer Phase I', 'healthy-volunteer-phase-1', 'healthy_phase1'),
            ('Heart and Blood Pressure', 'heart-and-blood-pressure', 'heart'),
            ('Lifestyle', 'lifestyle', 'lifestyle'),
            ('Mental Health', 'mental-health', 'mental_health'),
            ('Metabolic and Diabetes', 'metabolic-and-diabetes', 'metabolic'),
            ('Respiratory and Allergy', 'respiratory-and-allergy', 'respiratory'),
            ('Sleep', 'sleep', 'sleep'),
            ("Women's Health", 'womens-health', 'womens_health'),
        ]
        return {
            slug: StudyCategory.objects.update_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'ml_label': ml_label,
                    'description': f'Explore research about {name.lower()}.',
                    'display_order': order,
                },
            )[0]
            for order, (name, slug, ml_label) in enumerate(values, 1)
        }

    def create_organisations(self):
        values = [
            (
                'Harbourfront General Hospital',
                'hospital',
                'Nur Hidayah Salleh',
                'coordinator@harbourfront.sg',
            ),
            (
                'Kent Ridge Clinical Research Centre',
                'university',
                'Daniel Lim',
                'drlim@kentridge-crc.sg',
            ),
            (
                'Lion City Institute of Metabolic Health',
                'research_institute',
                'Kevin Ong',
                'coordinator@lioncity-imh.sg',
            ),
            (
                'Merlion Biotherapeutics',
                'sponsor',
                'Arun Pillai',
                'coordinator@merlionbio.sg',
            ),
            (
                'Straits Clinical Trials Pte Ltd',
                'cro',
                'Rachel Chua',
                'coordinator@straitsct.sg',
            ),
        ]
        return {
            name: Organisation.objects.update_or_create(
                name=name,
                defaults={
                    'org_type': org_type,
                    'contact_person': contact_person,
                    'contact_email': contact_email,
                },
            )[0]
            for name, org_type, contact_person, contact_email in values
        }

    def create_sites(self, organisations, regions):
        site_values = [
            (
                'Harbourfront General Hospital',
                'Harbourfront Main Campus',
                '1 Maritime Square, Block A',
                '099253',
                'C',
            ),
            (
                'Harbourfront General Hospital',
                'Harbourfront Community Clinic',
                '18 Telok Blangah Way',
                '098632',
                'C',
            ),
            (
                'Kent Ridge Clinical Research Centre',
                'Kent Ridge CRC, Lower Kent Ridge Clinic',
                '21 Lower Kent Ridge Road, Level 3',
                '119077',
                'W',
            ),
            (
                'Kent Ridge Clinical Research Centre',
                'Kent Ridge CRC, one-north Research Hub',
                '1 Fusionopolis Way',
                '138632',
                'W',
            ),
            (
                'Lion City Institute of Metabolic Health',
                'Lion City Metabolic Centre',
                '8 Yishun Central',
                '768828',
                'N',
            ),
            (
                'Lion City Institute of Metabolic Health',
                'Punggol Health Research Site',
                '10 Punggol Field',
                '828824',
                'NE',
            ),
            (
                'Merlion Biotherapeutics',
                'Merlion Biotherapeutics Lab',
                '31 Tai Seng Street',
                '534013',
                'E',
            ),
            (
                'Merlion Biotherapeutics',
                'Changi Research Clinic',
                '5 Upper Changi Road',
                '486886',
                'E',
            ),
            (
                'Straits Clinical Trials Pte Ltd',
                'Straits Novena Centre',
                '10 Thomson Road',
                '307727',
                'N',
            ),
            (
                'Straits Clinical Trials Pte Ltd',
                'Straits Pasir Ris Clinic',
                '21 Pasir Ris Drive',
                '519457',
                'E',
            ),
        ]
        sites = {}
        for org_name, name, address, postal_code, region_code in site_values:
            sites[name] = Site.objects.update_or_create(
                organisation=organisations[org_name],
                name=name,
                defaults={
                    'address': address,
                    'postal_code': postal_code,
                    'region': regions[region_code],
                },
            )[0]
        return sites

    def create_studies(self, organisations, categories, sites, regions, conditions):
        today = timezone.localdate()
        published_at = timezone.now()
        common = {
            'description': 'This plain-language study looks at health and daily life in Singapore.',
            'visit_plan': 'Visit 1 (week 1): consent and health questions (about 1 hour)\n'
            'Visit 2 (week 4): study activities and wellbeing check (about 1 hour)',
            'study_type': Study.StudyType.OBSERVATIONAL,
            'phase': Study.Phase.NOT_APPLICABLE,
            'accepts_healthy_volunteers': False,
            'sex_eligibility': Study.SexEligibility.ALL,
            'min_age': 21,
            'max_age': 65,
            'smoker_rule': Study.SmokerRule.ANY,
            'target_enrolment': 30,
            'total_visits': 2,
            'duration_weeks': 8,
            'visit_times': Study.VisitTimes.FLEXIBLE,
            'compensation_amount': '80.00',
            'show_compensation': True,
            'start_date': today,
            'irb_name': 'NUS-IRB',
            'irb_reference': 'NUS-ATHENA-2026-001',
            'irb_approved_text': True,
            'auto_shortlist_high': False,
        }
        entries = [
            ('Kopi, Teh and Blood Sugar: Measuring Local Drinks', 'metabolic-and-diabetes', 'Merlion Biotherapeutics', 'published'),
            ('Breathing Better with Singapore Allergies', 'respiratory-and-allergy', 'Harbourfront General Hospital', 'published'),
            ('Walking Routes and Everyday Heart Health', 'heart-and-blood-pressure', 'Straits Clinical Trials Pte Ltd', 'published'),
            ('A Good Night in the City', 'sleep', 'Lion City Institute of Metabolic Health', 'published'),
            ('Small Changes for Better Daily Movement', 'lifestyle', 'Straits Clinical Trials Pte Ltd', 'published'),
            ('Understanding Eczema in Humid Weather', 'respiratory-and-allergy', 'Harbourfront General Hospital', 'published'),
            ('Women and Migraine Triggers', 'womens-health', 'Straits Clinical Trials Pte Ltd', 'published'),
            ('Stress, Rest and Resilience', 'mental-health', 'Merlion Biotherapeutics', 'published'),
            ('Food Choices and Fatty Liver Health', 'metabolic-and-diabetes', 'Lion City Institute of Metabolic Health', 'published'),
            ('Digital Puzzles for Older Adults', 'cognitive', 'Harbourfront General Hospital', 'full'),
            ('Blood Pressure at Home', 'heart-and-blood-pressure', 'Merlion Biotherapeutics', 'full'),
            ('Healthy Volunteer Flu Vaccine Study', 'healthy-volunteer-phase-1', 'Harbourfront General Hospital', 'closed'),
            ('Morning Light and Mood', 'mental-health', 'Kent Ridge Clinical Research Centre', 'draft'),
            ('Healthy Ageing and Memory', 'cognitive', 'Lion City Institute of Metabolic Health', 'pending_review'),
            ('Neighbourhood Sleep and Shift Work', 'sleep', 'Straits Clinical Trials Pte Ltd', 'changes_requested'),
            ('Exercise and the Immune Response to a Seasonal Flu Vaccine', 'healthy-volunteer-phase-1', 'Kent Ridge Clinical Research Centre', 'published'),
            ('Healthy Volunteer Blood Sample Bank for Lab Test Development', 'healthy-volunteer-phase-1', 'Kent Ridge Clinical Research Centre', 'published'),
            ('Memory Games and Bilingual Brains', 'cognitive', 'Kent Ridge Clinical Research Centre', 'published'),
            ('Sleep Habits of Shift Workers', 'sleep', 'Kent Ridge Clinical Research Centre', 'published'),
            ('Asthma Care Around the Monsoon', 'respiratory-and-allergy', 'Harbourfront General Hospital', 'paused'),
        ]
        studies = {}
        for index, (title, category_slug, org_name, status) in enumerate(entries, 1):
            slug = title.lower().replace(':', '').replace(',', '').replace(' ', '-')
            slug = ''.join(character for character in slug if character.isalnum() or character == '-')
            deadline = today + timedelta(days=14 + (index % 9) * 7)
            defaults = {
                **common,
                'title': title,
                'slug': slug,
                'category': categories[category_slug],
                'organisation': organisations[org_name],
                'status': status,
                'recruitment_deadline': deadline,
                'irb_expiry': add_months(deadline, 3),
                'published_at': published_at - timedelta(days=index) if status in ('published', 'full') else None,
            }
            if status == 'full':
                defaults.update(target_enrolment=3)
            if status == 'changes_requested':
                defaults['moderation_comments'] = (
                    'Please explain what happens at visit 2 in plain language.'
                )
            if status == 'paused':
                defaults['paused_reason'] = 'IRB amendment under review'
            if title == 'Morning Light and Mood':
                defaults.update(
                    study_type=Study.StudyType.INTERVENTIONAL,
                    phase=Study.Phase.PHASE_2,
                    visit_times=Study.VisitTimes.WEEKDAY_DAYTIME,
                )
            if title == 'Exercise and the Immune Response to a Seasonal Flu Vaccine':
                defaults.update(
                    study_type=Study.StudyType.INTERVENTIONAL,
                    phase=Study.Phase.PHASE_4,
                    accepts_healthy_volunteers=True,
                    max_age=45,
                    total_visits=5,
                    duration_weeks=12,
                    visit_times=Study.VisitTimes.WEEKDAY_EVENINGS,
                    compensation_amount='350.00',
                    target_enrolment=40,
                )
            elif title == 'Healthy Volunteer Blood Sample Bank for Lab Test Development':
                defaults.update(
                    accepts_healthy_volunteers=True,
                    max_age=70,
                    total_visits=1,
                    duration_weeks=1,
                    compensation_amount='30.00',
                    target_enrolment=60,
                )
            elif title == 'Memory Games and Bilingual Brains':
                defaults.update(
                    study_type=Study.StudyType.BEHAVIOURAL,
                    accepts_healthy_volunteers=True,
                    max_age=75,
                )
            elif title == 'Sleep Habits of Shift Workers':
                defaults.update(max_age=60, show_compensation=False)
            if index in (2, 4, 6, 8, 10, 12):
                defaults['show_compensation'] = False
            if index in (1, 4, 6, 8, 10):
                defaults['accepts_healthy_volunteers'] = True
            study = Study.objects.update_or_create(slug=slug, defaults=defaults)[0]
            if title == 'Exercise and the Immune Response to a Seasonal Flu Vaccine':
                study.sites.set([
                    sites['Kent Ridge CRC, Lower Kent Ridge Clinic'],
                    sites['Kent Ridge CRC, one-north Research Hub'],
                ])
            elif title == 'Healthy Volunteer Blood Sample Bank for Lab Test Development':
                study.sites.set([sites['Kent Ridge CRC, Lower Kent Ridge Clinic']])
            else:
                study.sites.set(
                    list(Site.objects.filter(organisation=study.organisation)[:1])
                )
            if index in (1, 3, 5, 7):
                study.regions.set([regions['C'], regions['W']])
            if index in (1, 9, 17):
                study.min_bmi = '18.5'
                study.max_bmi = '30.0'
                study.save(update_fields=['min_bmi', 'max_bmi', 'updated_at'])
            if index == 1:
                study.required_conditions.set([conditions['Prediabetes']])
            if index == 2:
                study.excluded_conditions.set([conditions['Asthma']])
            studies[title] = study
        return studies

    def create_questions(self, studies):
        questions = {
            'Exercise and the Immune Response to a Seasonal Flu Vaccine': [
                ('Have you had a flu vaccine in the last 6 months?', 'Yes\nNo', 'No', 'Yes'),
                ('Can you exercise for 30 minutes three times a week?', 'Yes\nNo', 'Yes', ''),
            ],
            'Healthy Volunteer Blood Sample Bank for Lab Test Development': [
                ('Are you comfortable having a small blood sample taken?', 'Yes\nNo', 'Yes', 'No'),
                ('Do you have a strong fear of needles that makes you feel faint?', 'Yes\nNo', 'No', 'Yes'),
            ],
        }
        for title, study in studies.items():
            values = questions.get(title, [
                ('Are you able to attend the planned study visits?', 'Yes\nNo', 'Yes', 'No'),
                ('Have you read the study information?', 'Yes\nNo', 'Yes', ''),
                ('Would you like to ask the research team a question?', 'Yes\nNo', 'No', ''),
            ])
            for order, (text, options, preferred, disqualifying) in enumerate(values, 1):
                PreScreenQuestion.objects.update_or_create(
                    study=study,
                    order=order,
                    defaults={
                        'text': text,
                        'options': options,
                        'preferred_answer': preferred,
                        'disqualifying_answer': disqualifying,
                    },
                )
