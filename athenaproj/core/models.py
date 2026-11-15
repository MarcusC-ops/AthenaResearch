"""All Athena models live in this file."""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import (
    EmailValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models
from django.db.models import Q
from django.utils.text import slugify
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AccessRights(TimeStampedModel):
    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ('participant_access', 'Can access participant features'),
            ('panel_access', 'Can access the panel'),
            ('staff_access', 'Can access staff features'),
            ('admin_access', 'Can access admin features'),
        ]

    def __str__(self):
        return 'Access rights'


class Region(TimeStampedModel):
    code = models.CharField(
        max_length=2,
        unique=True,
        validators=[RegexValidator(r'^[A-Z]{1,2}$', 'Use one or two capital letters.')],
    )
    name = models.CharField(max_length=40)
    display_order = models.PositiveIntegerField()

    class Meta:
        ordering = ['display_order']

    def __str__(self):
        return f'{self.code} {self.name}'


class Condition(TimeStampedModel):
    class MLFlag(models.TextChoices):
        DIABETES = 'diabetes', 'Diabetes'
        HYPERTENSION = 'hypertension', 'Hypertension'
        HIGH_CHOLESTEROL = 'high_cholesterol', 'High cholesterol'
        RESPIRATORY = 'respiratory', 'Respiratory'
        MENTAL = 'mental', 'Mental'
        SLEEP = 'sleep', 'Sleep'
        SKIN = 'skin', 'Skin'

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True, blank=True)
    ml_flag = models.CharField(max_length=30, choices=MLFlag.choices, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class StudyCategory(TimeStampedModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    ml_label = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255)
    display_order = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['display_order']

    def __str__(self):
        return self.name


class Organisation(TimeStampedModel):
    class OrganisationType(models.TextChoices):
        HOSPITAL = 'hospital', 'Hospital'
        UNIVERSITY = 'university', 'University'
        RESEARCH_INSTITUTE = 'research_institute', 'Research institute'
        SPONSOR = 'sponsor', 'Sponsor'
        CRO = 'cro', 'Clinical research organisation'

    name = models.CharField(max_length=150, unique=True)
    org_type = models.CharField(max_length=30, choices=OrganisationType.choices)
    contact_person = models.CharField(max_length=120)
    contact_email = models.EmailField(validators=[EmailValidator()])
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Site(TimeStampedModel):
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=255)
    postal_code = models.CharField(
        max_length=6,
        validators=[RegexValidator(r'^\d{6}$', 'Postal code must contain exactly 6 digits.')],
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.RESTRICT, related_name='sites'
    )
    region = models.ForeignKey(Region, on_delete=models.RESTRICT, related_name='sites')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.organisation.name} - {self.name}'


class Study(TimeStampedModel):
    class StudyType(models.TextChoices):
        INTERVENTIONAL = 'interventional', 'Interventional'
        OBSERVATIONAL = 'observational', 'Observational'
        BEHAVIOURAL = 'behavioural', 'Behavioural'

    class Phase(models.TextChoices):
        NOT_APPLICABLE = 'not_applicable', 'Not applicable'
        PHASE_1 = 'phase_1', 'Phase I'
        PHASE_2 = 'phase_2', 'Phase II'
        PHASE_3 = 'phase_3', 'Phase III'
        PHASE_4 = 'phase_4', 'Phase IV'

    class SexEligibility(models.TextChoices):
        ALL = 'all', 'Anyone'
        FEMALE = 'female', 'Women only'
        MALE = 'male', 'Men only'

    class SmokerRule(models.TextChoices):
        ANY = 'any', 'Smokers and non-smokers'
        NON_SMOKERS = 'non_smokers', 'Non-smokers only'
        SMOKERS = 'smokers', 'Smokers only'

    class VisitTimes(models.TextChoices):
        WEEKDAY_DAYTIME = 'weekday_daytime', 'Weekday daytime'
        WEEKDAY_EVENINGS = 'weekday_evenings', 'Weekday evenings'
        WEEKENDS = 'weekends', 'Weekends'
        FLEXIBLE = 'flexible', 'Flexible'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PENDING_REVIEW = 'pending_review', 'Pending review'
        CHANGES_REQUESTED = 'changes_requested', 'Changes requested'
        PUBLISHED = 'published', 'Published'
        PAUSED = 'paused', 'Paused'
        FULL = 'full', 'Full'
        CLOSED = 'closed', 'Closed'

    organisation = models.ForeignKey(
        Organisation, on_delete=models.RESTRICT, related_name='studies'
    )
    category = models.ForeignKey(
        StudyCategory, on_delete=models.RESTRICT, related_name='studies'
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField()
    visit_plan = models.TextField(blank=True)
    study_type = models.CharField(max_length=20, choices=StudyType.choices)
    phase = models.CharField(
        max_length=20, choices=Phase.choices, default=Phase.NOT_APPLICABLE
    )
    accepts_healthy_volunteers = models.BooleanField()
    sex_eligibility = models.CharField(
        max_length=10, choices=SexEligibility.choices, default=SexEligibility.ALL
    )
    min_age = models.PositiveIntegerField(
        validators=[MinValueValidator(21), MaxValueValidator(100)]
    )
    max_age = models.PositiveIntegerField(
        validators=[MinValueValidator(21), MaxValueValidator(100)]
    )
    min_bmi = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    max_bmi = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    smoker_rule = models.CharField(
        max_length=15, choices=SmokerRule.choices, default=SmokerRule.ANY
    )
    required_conditions = models.ManyToManyField(
        Condition, blank=True, related_name='required_by_studies'
    )
    excluded_conditions = models.ManyToManyField(
        Condition, blank=True, related_name='excluded_by_studies'
    )
    regions = models.ManyToManyField(Region, blank=True, related_name='studies')
    sites = models.ManyToManyField(Site, blank=True, related_name='studies')
    target_enrolment = models.PositiveIntegerField()
    total_visits = models.PositiveIntegerField()
    duration_weeks = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )
    visit_times = models.CharField(max_length=20, choices=VisitTimes.choices)
    compensation_amount = models.DecimalField(max_digits=8, decimal_places=2)
    show_compensation = models.BooleanField()
    start_date = models.DateField()
    recruitment_deadline = models.DateField()
    irb_name = models.CharField(max_length=60, blank=True)
    irb_reference = models.CharField(max_length=60, blank=True)
    irb_expiry = models.DateField(null=True, blank=True)
    irb_approved_text = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    auto_shortlist_high = models.BooleanField(default=False)
    moderation_comments = models.TextField(blank=True)
    paused_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_studies',
    )
    last_edited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='edited_studies',
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_studies',
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(min_age__lte=models.F('max_age')),
                name='study_age_order',
            ),
            models.CheckConstraint(
                condition=Q(min_bmi__isnull=True)
                | Q(max_bmi__isnull=True)
                | Q(min_bmi__lte=models.F('max_bmi')),
                name='study_bmi_order',
            ),
            models.CheckConstraint(
                condition=Q(target_enrolment__gte=1),
                name='study_target_min_1',
            ),
            models.CheckConstraint(
                condition=Q(total_visits__gte=1),
                name='study_visits_min_1',
            ),
            models.CheckConstraint(
                condition=Q(compensation_amount__gte=0),
                name='study_compensation_not_negative',
            ),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        errors = {}
        if self.phase != self.Phase.NOT_APPLICABLE and self.study_type != self.StudyType.INTERVENTIONAL:
            errors['phase'] = 'Only interventional studies have a phase.'
        if (
            self.start_date
            and self.recruitment_deadline
            and self.recruitment_deadline <= self.start_date
        ):
            errors['recruitment_deadline'] = (
                'The recruitment deadline must be after the start date.'
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            candidate = base_slug
            suffix = 2
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base_slug}-{suffix}'
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def places_left(self):
        from .services import enrolled_count
        return max(0, self.target_enrolment - enrolled_count(self))


class PreScreenQuestion(TimeStampedModel):
    study = models.ForeignKey(
        Study, on_delete=models.CASCADE, related_name='pre_screen_questions'
    )
    text = models.CharField(max_length=250)
    order = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    options = models.TextField(default='Yes\nNo')
    preferred_answer = models.CharField(max_length=250, blank=True)
    disqualifying_answer = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.text

    def option_list(self):
        return [line.strip() for line in self.options.splitlines() if line.strip()]

    def clean(self):
        options = self.option_list()
        errors = {}
        if len(options) < 2:
            errors['options'] = 'At least two options are required.'
        if self.preferred_answer and self.preferred_answer not in options:
            errors['preferred_answer'] = 'Preferred answer must be one of the options.'
        if self.disqualifying_answer and self.disqualifying_answer not in options:
            errors['disqualifying_answer'] = (
                'Disqualifying answer must be one of the options.'
            )
        if errors:
            raise ValidationError(errors)


class ParticipantProfile(TimeStampedModel):
    class Sex(models.TextChoices):
        FEMALE = 'female', 'Female'
        MALE = 'male', 'Male'

    class Ethnicity(models.TextChoices):
        CHINESE = 'chinese', 'Chinese'
        MALAY = 'malay', 'Malay'
        INDIAN = 'indian', 'Indian'
        OTHERS = 'others', 'Others'
        PREFER_NOT = 'prefer_not', 'Prefer not to say'

    class Employment(models.TextChoices):
        STUDENT = 'student', 'Student'
        FULL_TIME = 'full_time', 'Employed full-time'
        PART_TIME = 'part_time', 'Employed part-time'
        NOT_WORKING = 'not_working', 'Not working'
        RETIRED = 'retired', 'Retired'

    class Education(models.TextChoices):
        PRIMARY = 'primary', 'Primary or below'
        SECONDARY = 'secondary', 'Secondary'
        POST_SECONDARY = 'post_secondary', 'Post-secondary (ITE, JC or polytechnic)'
        DEGREE = 'degree', "Bachelor's degree"
        POSTGRADUATE = 'postgraduate', 'Postgraduate'

    class ActivityLevel(models.TextChoices):
        LOW = 'low', 'Low (mostly sitting)'
        MODERATE = 'moderate', 'Moderate (some exercise each week)'
        HIGH = 'high', 'High (exercise most days)'

    class Motivation(models.TextChoices):
        HELP_RESEARCH = 'help_research', 'Helping research'
        HEALTH_CHECK = 'health_check', 'Access to health checks or new treatments'
        COMPENSATION = 'compensation', 'Compensation for my time'
        LEARN = 'learn', 'Learning about my health'

    class Availability(models.TextChoices):
        WEEKDAY_DAYTIME = 'weekday_daytime', 'Weekday daytime'
        WEEKDAY_EVENINGS = 'weekday_evenings', 'Weekday evenings'
        WEEKENDS = 'weekends', 'Weekends'
        FLEXIBLE = 'flexible', 'Flexible'

    class TravelMinutes(models.TextChoices):
        FIFTEEN = '15', 'Up to 15 minutes'
        THIRTY = '30', 'Up to 30 minutes'
        FORTY_FIVE = '45', 'Up to 45 minutes'
        SIXTY = '60', 'Up to an hour'

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='participant_profile'
    )
    mobile = models.CharField(max_length=11)
    terms_accepted_at = models.DateTimeField()
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=10, choices=Sex.choices, null=True, blank=True)
    region = models.ForeignKey(
        Region, on_delete=models.RESTRICT, null=True, blank=True,
        related_name='participant_profiles',
    )
    ethnicity = models.CharField(
        max_length=20, choices=Ethnicity.choices, null=True, blank=True
    )
    employment = models.CharField(
        max_length=20, choices=Employment.choices, null=True, blank=True
    )
    education = models.CharField(
        max_length=20, choices=Education.choices, null=True, blank=True
    )
    height_cm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    bmi = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    smoker = models.BooleanField(default=False)
    activity_level = models.CharField(
        max_length=20, choices=ActivityLevel.choices, null=True, blank=True
    )
    conditions = models.ManyToManyField(Condition, blank=True, related_name='participant_profiles')
    motivation = models.CharField(
        max_length=20, choices=Motivation.choices, null=True, blank=True
    )
    availability = models.CharField(
        max_length=20, choices=Availability.choices, null=True, blank=True
    )
    max_travel_minutes = models.CharField(
        max_length=2, choices=TravelMinutes.choices, null=True, blank=True
    )
    consent_matching = models.BooleanField(default=False)
    consent_insights = models.BooleanField(default=False)
    consent_contact = models.BooleanField(default=False)
    ml1_categories = models.JSONField(default=list, blank=True)
    ml1_model_version = models.CharField(max_length=50, blank=True)
    ml1_predicted_at = models.DateTimeField(null=True, blank=True)
    first_application_category = models.ForeignKey(
        'StudyCategory',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='first_applications',
    )

    def __str__(self):
        return f'{self.user.get_full_name()} profile'

    @property
    def code(self):
        return f'P-{self.user_id:05d}'

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = timezone.localdate()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )

    def save(self, *args, **kwargs):
        if self.height_cm and self.weight_kg:
            self.bmi = round(
                float(self.weight_kg) / (float(self.height_cm) / 100) ** 2, 1
            )
        else:
            self.bmi = None
        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'bmi'}
        super().save(*args, **kwargs)


class StaffProfile(TimeStampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='staff_profile')
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.RESTRICT,
        related_name='staff_profiles',
        null=True,
        blank=True,
    )
    job_title = models.CharField(max_length=100, blank=True)
    mobile = models.CharField(max_length=11)

    def __str__(self):
        return f'{self.user.get_full_name()} profile'


class Notification(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=255)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return self.message


class PredictionLog(TimeStampedModel):
    class ModelName(models.TextChoices):
        ML1 = 'ml1', 'ML-1'
        ML2 = 'ml2', 'ML-2'

    model_name = models.CharField(max_length=3, choices=ModelName.choices)
    model_version = models.CharField(max_length=50)
    participant = models.ForeignKey(
        ParticipantProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prediction_logs',
    )
    application = models.ForeignKey(
        'Application',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prediction_logs',
    )
    features = models.JSONField(default=dict)
    output = models.JSONField(default=dict)
    succeeded = models.BooleanField()
    error_message = models.TextField(blank=True)

    def __str__(self):
        return f'{self.model_name} prediction for {self.participant or "removed participant"}'


class Shortlist(TimeStampedModel):
    participant = models.ForeignKey(
        ParticipantProfile,
        on_delete=models.CASCADE,
        related_name='shortlists',
    )
    study = models.ForeignKey(
        Study,
        on_delete=models.CASCADE,
        related_name='shortlists',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['participant', 'study'],
                name='unique_shortlist_pair',
            ),
        ]

    def __str__(self):
        return f'{self.participant.code}: {self.study.title}'


class Application(TimeStampedModel):
    class Status(models.TextChoices):
        SUBMITTED = 'submitted', 'Submitted'
        AUTO_DECLINED = 'auto_declined', 'Auto-declined'
        UNDER_REVIEW = 'under_review', 'Under review'
        WAITLISTED = 'waitlisted', 'Waitlisted'
        SHORTLISTED = 'shortlisted', 'Shortlisted'
        SCREENING_SCHEDULED = 'screening_scheduled', 'Screening scheduled'
        SCREENING_PASSED = 'screening_passed', 'Screening passed'
        SCREENING_FAILED = 'screening_failed', 'Screening failed'
        ENROLLED = 'enrolled', 'Enrolled'
        COMPLETED = 'completed', 'Completed'
        NOT_SELECTED = 'not_selected', 'Not selected'
        WITHDRAWN = 'withdrawn', 'Withdrawn'

    class Band(models.TextChoices):
        HIGH = 'high', 'High'
        MEDIUM = 'medium', 'Medium'
        LOW = 'low', 'Low'
        UNSCORED = 'unscored', 'Unscored'

    class Availability(models.TextChoices):
        WEEKDAY_DAYTIME = 'weekday_daytime', 'Weekday daytime'
        WEEKDAY_EVENINGS = 'weekday_evenings', 'Weekday evenings'
        WEEKENDS = 'weekends', 'Weekends'
        FLEXIBLE = 'flexible', 'Flexible'

    class ScreeningOutcome(models.TextChoices):
        PASSED = 'passed', 'Passed'
        FAILED = 'failed', 'Failed'

    participant = models.ForeignKey(
        ParticipantProfile, on_delete=models.RESTRICT, related_name='applications'
    )
    study = models.ForeignKey(Study, on_delete=models.RESTRICT, related_name='applications')
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.SUBMITTED)
    preferred_site = models.ForeignKey(
        Site, on_delete=models.RESTRICT, related_name='applications'
    )
    availability = models.CharField(max_length=20, choices=Availability.choices)
    consent_given_at = models.DateTimeField()
    submitted_at = models.DateTimeField()
    ml2_probability = models.FloatField(null=True, blank=True)
    ml2_band = models.CharField(max_length=10, choices=Band.choices, default=Band.UNSCORED)
    ml2_model_version = models.CharField(max_length=50, blank=True)
    auto_shortlisted = models.BooleanField(default=False)
    original_band = models.CharField(max_length=10, choices=Band.choices, blank=True)
    band_overridden = models.BooleanField(default=False)
    override_reason = models.TextField(blank=True)
    overridden_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='overridden_applications',
    )
    overridden_at = models.DateTimeField(null=True, blank=True)
    screening_outcome = models.CharField(
        max_length=10, choices=ScreeningOutcome.choices, blank=True
    )
    outcome_recorded_at = models.DateTimeField(null=True, blank=True)
    not_selected_reason = models.TextField(blank=True)
    withdrawal_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['participant', 'study'], name='unique_application_pair'
            ),
        ]

    def __str__(self):
        return f'{self.reference}: {self.study.title}'

    @property
    def reference(self):
        return f'A-{self.pk:04d}'


class ApplicationAnswer(TimeStampedModel):
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='answers'
    )
    question = models.ForeignKey(
        PreScreenQuestion, on_delete=models.RESTRICT, related_name='application_answers'
    )
    answer = models.CharField(max_length=250)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'question'], name='unique_answer_per_question'
            ),
        ]

    def __str__(self):
        return f'{self.application.reference}: {self.question.text}'

    def clean(self):
        if self.question_id and self.answer not in self.question.option_list():
            raise ValidationError({'answer': 'Answer must be one of the question options.'})


class ApplicationStatusEvent(TimeStampedModel):
    class ActorRole(models.TextChoices):
        SYSTEM = 'system', 'Athena'
        PARTICIPANT = 'participant', 'You'
        COORDINATOR = 'coordinator', 'Research team'
        STAFF = 'staff', 'Athena team'

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='status_events'
    )
    from_status = models.CharField(max_length=25, choices=Application.Status.choices, blank=True)
    to_status = models.CharField(max_length=25, choices=Application.Status.choices)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='application_events'
    )
    actor_role = models.CharField(max_length=15, choices=ActorRole.choices, default=ActorRole.SYSTEM)
    note = models.TextField(blank=True)

    def __str__(self):
        return f'{self.application.reference}: {self.to_status}'


class AppSetting(TimeStampedModel):
    ml2_high_threshold = models.FloatField(default=0.70)
    ml2_medium_threshold = models.FloatField(default=0.40)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='updated_app_settings',
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(ml2_medium_threshold__gt=0)
                & Q(ml2_medium_threshold__lt=models.F('ml2_high_threshold'))
                & Q(ml2_high_threshold__lt=1),
                name='appsetting_threshold_order',
            ),
        ]

    def __str__(self):
        return 'Athena application settings'
