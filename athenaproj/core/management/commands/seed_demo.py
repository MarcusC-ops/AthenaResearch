"""Create the realistic, repeatable Athena demonstration catalogue."""

import calendar
import os
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, User
from django.utils import timezone

from core.models import (
    Appointment,
    Application,
    Condition,
    Organisation,
    Payout,
    PreScreenQuestion,
    PredictionLog,
    Region,
    Review,
    Site,
    Study,
    StudyCategory,
    SupportRequest,
    ParticipantProfile,
    Shortlist,
    StaffProfile,
)
from core.validators import normalise_sg_mobile
from core.services import (
    change_status,
    enrol_applicant,
    is_eligible,
    override_band,
    record_screening_outcome,
    schedule_screening,
    shortlist_applicant,
    submit_application,
    waitlist_applicant,
)


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
        self.create_after_sales(studies, sites)
        self.create_shortlists(studies)

        for label, model in (
            ('Regions', Region),
            ('Conditions', Condition),
            ('Categories', StudyCategory),
            ('Organisations', Organisation),
            ('Sites', Site),
            ('Studies', Study),
            ('Pre-screen questions', PreScreenQuestion),
            ('Applications', Application),
            ('Appointments', Appointment),
            ('Payouts', Payout),
            ('Reviews', Review),
            ('Support requests', SupportRequest),
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
        total_applications = Application.objects.filter(
            participant__user__username__startswith='demo'
        ).count()
        if total_applications >= 30:
            return
        public_studies = [
            study for study in studies.values() if study.status in (Study.Status.PUBLISHED, Study.Status.FULL)
        ]
        for profile in applicants:
            for study in public_studies:
                if total_applications >= 30:
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
                    total_applications += 1

    def create_after_sales(self, studies, sites):
        flu_study = studies['Exercise and the Immune Response to a Seasonal Flu Vaccine']
        blood_study = studies['Healthy Volunteer Blood Sample Bank for Lab Test Development']
        metabolic_study = studies['Food Choices and Fatty Liver Health']
        memory_study = studies['Memory Games and Bilingual Brains']
        aisyah = ParticipantProfile.objects.get(user__username='aisyah@example.com')
        mr_tan = ParticipantProfile.objects.get(user__username='mrtan@example.com')

        self.create_order_management_applications(flu_study, sites)
        aisyah_application = self.get_or_submit_application(
            aisyah,
            flu_study,
            sites['Kent Ridge CRC, Lower Kent Ridge Clinic'],
        )
        self.create_aisyah_after_sales(
            aisyah_application,
            sites['Kent Ridge CRC, Lower Kent Ridge Clinic'],
        )

        self.get_or_submit_application(
            mr_tan,
            blood_study,
            sites['Kent Ridge CRC, Lower Kent Ridge Clinic'],
            disqualify=True,
        )
        self.get_or_submit_application(
            mr_tan,
            metabolic_study,
            metabolic_study.sites.first(),
        )

        ratings = [5, 4, 4, 3]
        for index, rating in enumerate(ratings, 1):
            profile = ParticipantProfile.objects.get(
                user__username=f'demo{index:02d}@example.com'
            )
            application = self.get_or_submit_application(
                profile,
                memory_study,
                memory_study.sites.first(),
            )
            self.move_application_to(application, Application.Status.COMPLETED)
            Review.objects.update_or_create(
                participant=profile,
                study=memory_study,
                defaults={
                    'rating': rating,
                    'comment': (
                        'The study team explained each step clearly.'
                        if index == 1 else ''
                    ),
                    'status': Review.Status.APPROVED,
                    'rejection_reason': '',
                    'moderated_by': None,
                    'moderated_at': timezone.now(),
                },
            )

        pending_profile = ParticipantProfile.objects.get(
            user__username='demo05@example.com'
        )
        pending_application = self.get_or_submit_application(
            pending_profile,
            memory_study,
            memory_study.sites.first(),
        )
        self.move_application_to(pending_application, Application.Status.COMPLETED)
        Review.objects.update_or_create(
            participant=pending_profile,
            study=memory_study,
            defaults={
                'rating': 5,
                'comment': 'A clear and interesting experience.',
                'status': Review.Status.PENDING,
                'rejection_reason': '',
                'moderated_by': None,
                'moderated_at': None,
            },
        )

    def create_order_management_applications(self, study, sites):
        applicants = [
            (
                'aisyah@example.com',
                Application.Status.ENROLLED,
                0.82,
                Application.Band.HIGH,
            ),
            (
                'demo01@example.com',
                Application.Status.ENROLLED,
                0.80,
                Application.Band.HIGH,
            ),
            (
                'demo02@example.com',
                Application.Status.ENROLLED,
                0.55,
                Application.Band.MEDIUM,
            ),
            (
                'demo03@example.com',
                Application.Status.ENROLLED,
                0.20,
                Application.Band.LOW,
            ),
            (
                'demo04@example.com',
                Application.Status.ENROLLED,
                None,
                Application.Band.UNSCORED,
            ),
            (
                'demo05@example.com',
                Application.Status.WAITLISTED,
                0.55,
                Application.Band.MEDIUM,
            ),
            (
                'demo06@example.com',
                Application.Status.SHORTLISTED,
                0.65,
                Application.Band.MEDIUM,
            ),
            (
                'demo07@example.com',
                Application.Status.SHORTLISTED,
                0.35,
                Application.Band.LOW,
            ),
            (
                'demo08@example.com',
                Application.Status.SCREENING_SCHEDULED,
                0.82,
                Application.Band.HIGH,
            ),
            (
                'demo09@example.com',
                Application.Status.SCREENING_PASSED,
                0.55,
                Application.Band.MEDIUM,
            ),
            (
                'demo10@example.com',
                Application.Status.UNDER_REVIEW,
                0.20,
                Application.Band.LOW,
            ),
            (
                'demo11@example.com',
                Application.Status.UNDER_REVIEW,
                0.75,
                Application.Band.HIGH,
            ),
            (
                'demo12@example.com',
                Application.Status.UNDER_REVIEW,
                None,
                Application.Band.UNSCORED,
            ),
            (
                'demo13@example.com',
                Application.Status.UNDER_REVIEW,
                0.25,
                Application.Band.LOW,
            ),
        ]
        site = sites['Kent Ridge CRC, Lower Kent Ridge Clinic']
        coordinator = User.objects.get(username='drlim@kentridge-crc.sg')
        scheduled_for = timezone.now() + timedelta(days=3)

        for username, target_status, probability, band in applicants:
            profile = ParticipantProfile.objects.get(user__username=username)
            application = self.get_or_submit_application(profile, study, site)
            self._set_demo_prediction(application, probability, band)
            self._move_demo_application(
                application,
                target_status,
                site,
                coordinator,
                scheduled_for,
            )
            if username == 'demo06@example.com' and not application.band_overridden:
                application.ml2_band = Application.Band.MEDIUM
                application.save(update_fields=['ml2_band', 'updated_at'])
                override_band(
                    application,
                    Application.Band.HIGH,
                    'Coordinator review supports this stronger match.',
                    coordinator,
                )

    def _set_demo_prediction(self, application, probability, band):
        prediction = application.prediction_logs.filter(
            model_name=PredictionLog.ModelName.ML2
        ).order_by('-created_at', '-pk').first()
        application.ml2_probability = probability
        if not application.band_overridden:
            application.ml2_band = band
        application.ml2_model_version = (
            prediction.model_version if prediction else 'ml2-v1.0'
        )
        application.save(update_fields=[
            'ml2_probability',
            'ml2_band',
            'ml2_model_version',
            'updated_at',
        ])
        if prediction and prediction.succeeded:
            prediction.output = {
                'probability': probability,
                'band': band,
            }
            prediction.save(update_fields=['output', 'updated_at'])

    def _move_demo_application(
        self, application, target_status, site, coordinator, scheduled_for
    ):
        if application.status == target_status:
            return
        if application.status == Application.Status.SUBMITTED:
            change_status(
                application,
                Application.Status.UNDER_REVIEW,
                actor=coordinator,
                actor_role='coordinator',
                note='Application reviewed for the demonstration.',
            )
        if application.status == Application.Status.UNDER_REVIEW:
            if target_status == Application.Status.UNDER_REVIEW:
                return
            shortlist_applicant(application, coordinator)
        if target_status == Application.Status.SHORTLISTED:
            return
        if application.status == Application.Status.SHORTLISTED:
            screening_time = (
                scheduled_for
                if target_status == Application.Status.SCREENING_SCHEDULED
                else timezone.now() + timedelta(days=1)
            )
            schedule_screening(
                application,
                screening_time,
                site,
                coordinator,
            )
        if target_status == Application.Status.SCREENING_SCHEDULED:
            return
        if application.status == Application.Status.SCREENING_SCHEDULED:
            record_screening_outcome(application, True, coordinator)
        if target_status == Application.Status.SCREENING_PASSED:
            return
        if target_status == Application.Status.WAITLISTED:
            waitlist_applicant(application, coordinator)
        elif target_status == Application.Status.ENROLLED:
            enrol_applicant(application, coordinator)
        elif target_status != Application.Status.UNDER_REVIEW:
            raise ValueError(f'Cannot seed {target_status} from {application.status}.')

    def get_or_submit_application(
        self, profile, study, site, disqualify=False
    ):
        questions = list(study.pre_screen_questions.all())
        answers = {}
        for question in questions:
            answer = question.preferred_answer or question.option_list()[0]
            if disqualify and question.disqualifying_answer:
                answer = question.disqualifying_answer
            answers[question.pk] = answer
        application, _ = submit_application(
            profile,
            study,
            answers,
            site.pk,
            profile.availability or Application.Availability.FLEXIBLE,
            True,
        )
        return application

    def move_application_to(self, application, target_status):
        if application.status == target_status:
            return
        path = [
            Application.Status.UNDER_REVIEW,
            Application.Status.SHORTLISTED,
            Application.Status.SCREENING_SCHEDULED,
            Application.Status.SCREENING_PASSED,
            Application.Status.ENROLLED,
        ]
        if target_status == Application.Status.COMPLETED:
            path.append(Application.Status.COMPLETED)
        if application.status in (
            Application.Status.SUBMITTED,
            Application.Status.WAITLISTED,
        ):
            change_status(
                application,
                Application.Status.UNDER_REVIEW,
                actor_role='coordinator',
                note='Application reviewed for the demonstration.',
            )
        if application.status not in path:
            raise ValueError(
                f'Cannot seed {target_status} from {application.status}.'
            )
        start = path.index(application.status) + 1
        for status in path[start:]:
            change_status(
                application,
                status,
                actor_role='coordinator',
                note='Demonstration application progress.',
            )

    def create_aisyah_after_sales(self, application, site):
        now = timezone.now()
        screening_at = timezone.make_aware(
            datetime(2026, 9, 8, 18, 30),
            timezone.get_current_timezone(),
        )
        Appointment.objects.update_or_create(
            application=application,
            kind=Appointment.Kind.SCREENING,
            visit_number=None,
            defaults={
                'site': site,
                'scheduled_for': screening_at,
                'status': Appointment.Status.ATTENDED,
                'confirmed_at': screening_at - timedelta(days=1),
            },
        )
        today = timezone.localdate()
        visit_dates = [
            today - timedelta(days=42),
            today - timedelta(days=28),
            today - timedelta(days=14),
            today + timedelta(days=7),
            today + timedelta(days=21),
        ]
        visit_statuses = [
            Appointment.Status.ATTENDED,
            Appointment.Status.ATTENDED,
            Appointment.Status.ATTENDED,
            Appointment.Status.CONFIRMED,
            Appointment.Status.PROPOSED,
        ]
        for number, (visit_date, status) in enumerate(
            zip(visit_dates, visit_statuses),
            1,
        ):
            scheduled_for = timezone.make_aware(
                datetime.combine(visit_date, time(18, 0)),
                timezone.get_current_timezone(),
            )
            Appointment.objects.update_or_create(
                application=application,
                kind=Appointment.Kind.VISIT,
                visit_number=number,
                defaults={
                    'site': site,
                    'scheduled_for': scheduled_for,
                    'status': status,
                    'confirmed_at': (
                        now - timedelta(days=1)
                        if status == Appointment.Status.CONFIRMED else None
                    ),
                },
            )
        Payout.objects.update_or_create(
            application=application,
            reference='PN-2026-000001',
            defaults={
                'amount': '140.00',
                'visits_counted': 3,
                'status': Payout.Status.PAID,
                'requested_by': None,
                'paid_by': None,
                'paid_at': now - timedelta(days=35),
                'rejection_reason': '',
            },
        )
        SupportRequest.objects.get_or_create(
            application=application,
            topic=SupportRequest.Topic.COMPENSATION,
            question='When will my next payout be made?',
            defaults={
                'status': SupportRequest.Status.OPEN,
                'reply': '',
                'replied_by': None,
                'replied_at': None,
            },
        )

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
            elif title == 'Food Choices and Fatty Liver Health':
                defaults.update(max_age=70)
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
