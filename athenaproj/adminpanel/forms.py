from django import forms

from core.models import (
    Application, Appointment, Condition, Organisation, PreScreenQuestion, Site,
    Study, StudyCategory,
)
from core.validators import normalise_sg_mobile


class StudyForm(forms.ModelForm):
    class Meta:
        model = Study
        fields = [
            'title',
            'category',
            'study_type',
            'phase',
            'description',
            'visit_plan',
            'accepts_healthy_volunteers',
            'sex_eligibility',
            'min_age',
            'max_age',
            'min_bmi',
            'max_bmi',
            'smoker_rule',
            'required_conditions',
            'excluded_conditions',
            'regions',
            'sites',
            'target_enrolment',
            'total_visits',
            'duration_weeks',
            'visit_times',
            'compensation_amount',
            'show_compensation',
            'start_date',
            'recruitment_deadline',
            'irb_name',
            'irb_reference',
            'irb_expiry',
            'irb_approved_text',
            'auto_shortlist_high',
        ]
        labels = {
            'accepts_healthy_volunteers': 'Healthy volunteers welcome',
            'sex_eligibility': 'Sex',
            'min_age': 'Minimum age',
            'max_age': 'Maximum age',
            'min_bmi': 'Minimum BMI',
            'max_bmi': 'Maximum BMI',
            'smoker_rule': 'Smoking',
            'required_conditions': 'Must have',
            'excluded_conditions': 'Not suitable if they have',
            'regions': 'Where participants must live (regions; leave empty for anywhere)',
            'target_enrolment': 'Target enrolment',
            'total_visits': 'Total visits',
            'duration_weeks': 'Duration (weeks)',
            'visit_times': 'Visit times',
            'compensation_amount': 'Amount (S$)',
            'show_compensation': 'Show the amount on the listing',
            'start_date': 'Start date',
            'recruitment_deadline': 'Recruitment deadline',
            'irb_expiry': 'IRB approval expiry',
            'irb_approved_text': 'The listing text is the version approved by the IRB',
            'auto_shortlist_high': 'Auto-shortlist High band applicants',
        }
        help_texts = {
            'description': (
                'Plain language. Do not use payment-led wording such as earn, free or '
                'guaranteed (BR-11).'
            ),
            'visit_plan': 'One line per visit.',
            'show_compensation': (
                'Tick only if the ethics board approved showing the amount.'
            ),
            'auto_shortlist_high': (
                'When on, applicants the screening model rates High move straight to '
                'Shortlisted (BR-08). You can change this at any time.'
            ),
        }

    def __init__(self, *args, organisation=None, staff_mode=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff_mode = staff_mode
        self.organisation = organisation or getattr(self.instance, 'organisation', None)
        categories = StudyCategory.objects.filter(is_active=True)
        conditions = Condition.objects.filter(is_active=True)
        if staff_mode and self.instance.pk:
            categories = categories | StudyCategory.objects.filter(
                pk=self.instance.category_id
            )
            conditions = conditions | Condition.objects.filter(
                pk__in=self.instance.required_conditions.values('pk')
            ) | Condition.objects.filter(
                pk__in=self.instance.excluded_conditions.values('pk')
            )
        self.fields['category'].queryset = categories.order_by('display_order')
        self.fields['required_conditions'].queryset = conditions.order_by('name')
        self.fields['excluded_conditions'].queryset = conditions.order_by('name')
        site_queryset = Site.objects.filter(
            organisation=self.organisation,
        )
        if not staff_mode:
            site_queryset = site_queryset.filter(is_active=True)
        self.fields['sites'].queryset = site_queryset.order_by('name').distinct()

        for field in self.fields.values():
            if isinstance(field.widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'
        for name in ('required_conditions', 'excluded_conditions', 'regions', 'sites'):
            self.fields[name].widget = forms.CheckboxSelectMultiple(
                attrs={'class': 'form-check-input'}
            )
        self.fields['description'].widget = forms.Textarea(
            attrs={'class': 'form-control', 'rows': 4}
        )
        self.fields['visit_plan'].widget = forms.Textarea(
            attrs={'class': 'form-control', 'rows': 4}
        )
        for name in ('start_date', 'recruitment_deadline', 'irb_expiry'):
            self.fields[name].widget = forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'}
            )
        for name in (
            'show_compensation',
            'accepts_healthy_volunteers',
            'irb_approved_text',
            'auto_shortlist_high',
        ):
            self.fields[name].widget.attrs['class'] = 'form-check-input'

    def clean(self):
        cleaned_data = super().clean()
        minimum_age = cleaned_data.get('min_age')
        maximum_age = cleaned_data.get('max_age')
        if (
            minimum_age is not None
            and maximum_age is not None
            and maximum_age < minimum_age
        ):
            self.add_error('max_age', 'Maximum age must be at least the minimum age.')

        minimum_bmi = cleaned_data.get('min_bmi')
        maximum_bmi = cleaned_data.get('max_bmi')
        if (
            minimum_bmi is not None
            and maximum_bmi is not None
            and maximum_bmi < minimum_bmi
        ):
            self.add_error('max_bmi', 'Maximum BMI must be at least the minimum BMI.')

        start_date = cleaned_data.get('start_date')
        deadline = cleaned_data.get('recruitment_deadline')
        if start_date and deadline and deadline <= start_date:
            self.add_error(
                'recruitment_deadline',
                'The recruitment deadline must be after the start date.',
            )

        study_type = cleaned_data.get('study_type')
        phase = cleaned_data.get('phase')
        if (
            study_type
            and phase
            and phase != Study.Phase.NOT_APPLICABLE
            and study_type != Study.StudyType.INTERVENTIONAL
        ):
            self.add_error('phase', 'Only interventional studies have a phase.')

        required = cleaned_data.get('required_conditions')
        excluded = cleaned_data.get('excluded_conditions')
        if required is not None and excluded is not None:
            if required.filter(pk__in=excluded.values('pk')).exists():
                self.add_error(
                    'excluded_conditions',
                    'A condition cannot be both required and excluded.',
                )

        sites = cleaned_data.get('sites')
        if sites is not None:
            allowed_site_ids = set(self.fields['sites'].queryset.values_list('pk', flat=True))
            if not sites.exists():
                self.add_error('sites', 'Choose at least one site.')
            elif any(site.pk not in allowed_site_ids for site in sites):
                self.add_error('sites', 'Choose sites from your organisation.')
        return cleaned_data


class ModerationCommentsForm(forms.Form):
    comments = forms.CharField(
        label='Comments for the coordinator',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
    )


class ReasonForm(forms.Form):
    reason = forms.CharField(
        label='Reason',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
    )


class OrganisationForm(forms.ModelForm):
    class Meta:
        model = Organisation
        fields = ['name', 'org_type', 'contact_person', 'contact_email']
        labels = {
            'name': 'Name',
            'org_type': 'Type',
            'contact_person': 'Contact person',
            'contact_email': 'Contact email',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = (
                'form-select' if isinstance(field.widget, forms.Select)
                else 'form-control'
            )


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ['name', 'address', 'postal_code', 'region']
        labels = {
            'name': 'Name',
            'address': 'Address',
            'postal_code': 'Postal code',
            'region': 'Region',
        }

    def __init__(self, *args, organisation, **kwargs):
        super().__init__(*args, **kwargs)
        self.organisation = organisation
        for field in self.fields.values():
            field.widget.attrs['class'] = (
                'form-select' if isinstance(field.widget, forms.Select)
                else 'form-control'
            )

    def save(self, commit=True):
        site = super().save(commit=False)
        site.organisation = self.organisation
        if commit:
            site.save()
            self.save_m2m()
        return site


class CoordinatorForm(forms.Form):
    first_name = forms.CharField(
        label='First name', max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    last_name = forms.CharField(
        label='Last name', max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    email = forms.EmailField(
        label='Email', widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )
    job_title = forms.CharField(
        label='Job title', max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    mobile = forms.CharField(
        label='Mobile', widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    temporary_password = forms.CharField(
        label='Temporary password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        from django.contrib.auth.models import User
        if User.objects.filter(username=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean_mobile(self):
        return normalise_sg_mobile(self.cleaned_data['mobile'])


class CategoryForm(forms.ModelForm):
    ml_label = forms.CharField(
        label='ML label',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = StudyCategory
        fields = ['name', 'slug', 'ml_label', 'description', 'display_order']
        labels = {
            'name': 'Name',
            'slug': 'Slug',
            'description': 'Description',
            'display_order': 'Order',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        if self.instance.pk:
            self.fields['ml_label'].disabled = True
        else:
            self.fields['ml_label'].help_text = (
                'This label will not be predicted until ML-1 is retrained.'
            )


class ConditionForm(forms.ModelForm):
    class Meta:
        model = Condition
        fields = ['name', 'ml_flag']
        labels = {'name': 'Name', 'ml_flag': 'ML flag'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = (
                'form-select' if isinstance(field.widget, forms.Select)
                else 'form-control'
            )


class PreScreenQuestionForm(forms.ModelForm):
    class Meta:
        model = PreScreenQuestion
        fields = ['text', 'options', 'preferred_answer', 'disqualifying_answer', 'order']
        labels = {
            'text': 'Question',
            'options': 'Options (one per line)',
            'preferred_answer': 'Preferred answer (optional)',
            'disqualifying_answer': 'Disqualifying answer (optional)',
            'order': 'Order',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        self.fields['options'].widget = forms.Textarea(
            attrs={'class': 'form-control', 'rows': 4}
        )


class ApplicantFilterForm(forms.Form):
    band = forms.ChoiceField(
        required=False,
        label='Band',
        choices=[('', 'All bands'), *Application.Band.choices],
    )
    site = forms.ModelChoiceField(
        queryset=Site.objects.none(),
        required=False,
        label='Preferred site',
    )
    availability = forms.ChoiceField(
        required=False,
        label='Availability',
        choices=[('', 'All availability'), *Study.VisitTimes.choices],
    )

    def __init__(self, *args, study, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['site'].queryset = study.sites.order_by('name')
        self.fields['site'].empty_label = 'All sites'

        for field in self.fields.values():
            field.widget.attrs['class'] = (
                'form-select' if isinstance(field.widget, forms.Select) else 'form-control'
            )


class ScreeningScheduleForm(forms.Form):
    when = forms.DateTimeField(
        label='Date and time',
        widget=forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M',
            attrs={'class': 'form-control', 'type': 'datetime-local'},
        ),
    )
    site = forms.ModelChoiceField(
        queryset=Site.objects.none(),
        label='Site',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, study, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['site'].queryset = study.sites.order_by('name')


class NotSelectedForm(forms.Form):
    reason = forms.CharField(
        required=False,
        label='Reason',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )


class ScreeningOutcomeForm(forms.Form):
    note = forms.CharField(
        required=False,
        label='Note',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )


class OverrideBandForm(forms.Form):
    new_band = forms.ChoiceField(
        label='New band',
        widget=forms.RadioSelect,
    )
    reason = forms.CharField(
        label='Reason',
        min_length=10,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )

    def __init__(self, *args, current_band, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_band'].choices = [
            choice for choice in Application.Band.choices
            if choice[0] != current_band and choice[0] != Application.Band.UNSCORED
        ]
        self.fields['new_band'].widget.attrs['class'] = 'form-check-input'

    def clean_reason(self):
        reason = self.cleaned_data['reason'].strip()
        if len(reason) < 10:
            raise forms.ValidationError(
                'Give a reason of at least 10 characters.'
            )
        return reason


class VisitDateForm(forms.Form):
    scheduled_for = forms.DateTimeField(
        label='Date and time',
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
    )

    def __init__(self, *args, appointment, **kwargs):
        super().__init__(*args, **kwargs)
        self.appointment = appointment


class ParticipationFilterForm(forms.Form):
    study_id = forms.ModelChoiceField(
        queryset=Study.objects.none(),
        label='Study',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, organisation, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['study_id'].queryset = Study.objects.filter(
            organisation=organisation,
            status__in=[Study.Status.PUBLISHED, Study.Status.PAUSED, Study.Status.FULL],
        ).order_by('title')
        self.fields['study_id'].empty_label = 'All our studies'


class CoordinatorWithdrawForm(forms.Form):
    reason = forms.CharField(
        required=False,
        label='Reason to show participant',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
