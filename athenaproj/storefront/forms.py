from django import forms
from django.utils import timezone

from core.models import (
    Application,
    Condition,
    ParticipantProfile,
    Study,
    StudyCategory,
    SupportRequest,
)
from core.services import list_regions


class LenientChoiceField(forms.ChoiceField):
    def valid_value(self, value):
        return True

    def clean(self, value):
        value = super().clean(value)
        return value if any(str(choice[0]) == str(value) for choice in self.choices) else ''


class LenientMultipleChoiceField(forms.MultipleChoiceField):
    def valid_value(self, value):
        return True

    def clean(self, value):
        values = super().clean(value)
        valid_values = {str(choice[0]) for choice in self.choices}
        return [item for item in values if str(item) in valid_values]


class StudyFilterForm(forms.Form):
    q = forms.CharField(required=False)
    category = LenientChoiceField(
        required=False,
        choices=(),
        widget=forms.Select,
    )
    type = LenientMultipleChoiceField(
        required=False,
        choices=Study.StudyType.choices,
        widget=forms.CheckboxSelectMultiple,
    )
    region = LenientChoiceField(required=False, choices=(), widget=forms.Select)
    duration = LenientChoiceField(
        required=False,
        choices=[
            ('', 'Any length'),
            ('short', 'Up to 4 weeks'),
            ('medium', '1 to 3 months'),
            ('long', 'Over 3 months'),
        ],
        widget=forms.Select,
    )
    hv = forms.BooleanField(required=False)
    comp = LenientChoiceField(
        required=False,
        choices=[
            ('', 'Any'),
            ('shown', 'Amount shown'),
            ('100', '$100 or more'),
            ('300', '$300 or more'),
        ],
        widget=forms.Select,
    )
    sort = LenientChoiceField(
        required=False,
        choices=[
            ('newest', 'Newest first'),
            ('deadline', 'Closing soon'),
            ('compensation', 'Highest compensation'),
            ('title', 'Title A to Z'),
        ],
        widget=forms.Select,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].choices = [('', 'All categories')] + list(
            StudyCategory.objects.filter(is_active=True)
            .order_by('display_order')
            .values_list('slug', 'name')
        )
        self.fields['region'].choices = [('', 'Anywhere')] + list(
            list_regions().values_list('code', 'name')
        )


class ApplyQuestionsForm(forms.Form):
    def __init__(self, study, *args, **kwargs):
        self.study = study
        super().__init__(*args, **kwargs)
        for question in study.pre_screen_questions.all():
            self.fields[f'question_{question.pk}'] = forms.ChoiceField(
                label=question.text,
                choices=[(option, option) for option in question.option_list()],
                widget=forms.RadioSelect,
            )
        self.fields['preferred_site'] = forms.ModelChoiceField(
            label='Preferred site',
            queryset=study.sites.all(),
            empty_label='Blank',
        )
        self.fields['availability'] = forms.ChoiceField(
            label='When you are usually free',
            choices=Application.Availability.choices,
            widget=forms.RadioSelect,
        )

    def cleaned_answers(self):
        answers = {}
        for field_name, value in self.cleaned_data.items():
            if field_name.startswith('question_'):
                question_id = int(field_name.split('_', 1)[1])
                answers[question_id] = value
        return answers


class WithdrawalForm(forms.Form):
    reason = forms.CharField(
        required=False,
        label='Reason (optional)',
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
    )


class ReviewForm(forms.Form):
    rating = forms.ChoiceField(
        label='How would you rate this study?',
        choices=[(rating, str(rating)) for rating in range(1, 6)],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
    )
    comment = forms.CharField(
        required=False,
        max_length=1000,
        label='Tell others what to expect (optional)',
        widget=forms.Textarea(attrs={'rows': 5, 'class': 'form-control'}),
    )


class SupportRequestForm(forms.Form):
    topic = forms.ChoiceField(
        label='What is it about?',
        choices=[('', 'Choose one'), *SupportRequest.Topic.choices],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    question = forms.CharField(
        max_length=1000,
        label='Your question',
        widget=forms.Textarea(attrs={'rows': 5, 'class': 'form-control'}),
    )


class ProfileForm(forms.ModelForm):
    class Meta:
        model = ParticipantProfile
        fields = [
            'date_of_birth', 'sex', 'region', 'ethnicity', 'employment',
            'education', 'height_cm', 'weight_kg', 'activity_level', 'smoker',
            'conditions', 'motivation', 'availability', 'max_travel_minutes',
            'consent_matching', 'consent_insights', 'consent_contact',
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'sex': forms.RadioSelect,
            'height_cm': forms.NumberInput(attrs={'min': '120', 'max': '220', 'step': '0.1'}),
            'weight_kg': forms.NumberInput(attrs={'min': '30', 'max': '250', 'step': '0.1'}),
            'conditions': forms.CheckboxSelectMultiple,
        }
        labels = {
            'date_of_birth': 'Date of birth',
            'sex': 'Sex',
            'region': 'Region',
            'ethnicity': 'Ethnicity (optional)',
            'employment': 'Employment',
            'education': 'Highest education',
            'height_cm': 'Height (cm)',
            'weight_kg': 'Weight (kg)',
            'activity_level': 'Activity level',
            'smoker': 'Smoker',
            'conditions': 'Known health conditions',
            'motivation': 'What matters most to you?',
            'availability': 'When are you usually free?',
            'max_travel_minutes': 'How far would you travel?',
            'consent_matching': 'Use my profile to recommend studies to me',
            'consent_insights': 'Include my answers in anonymised insights for research teams',
            'consent_contact': 'Research teams may contact me about studies I apply to',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in (
            'date_of_birth', 'sex', 'region', 'employment', 'height_cm',
            'weight_kg', 'activity_level', 'motivation', 'availability',
            'max_travel_minutes',
        ):
            self.fields[field_name].required = True
        self.fields['conditions'].queryset = Condition.objects.filter(
            is_active=True
        ).order_by('name')
        self.fields['height_cm'].validators = []
        self.fields['weight_kg'].validators = []

    def clean_date_of_birth(self):
        value = self.cleaned_data['date_of_birth']
        today = timezone.localdate()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 21:
            raise forms.ValidationError('You must be at least 21 to join Athena.')
        return value

    def clean_height_cm(self):
        value = self.cleaned_data['height_cm']
        if value < 120 or value > 220:
            raise forms.ValidationError('Enter a height between 120 and 220 cm.')
        return value

    def clean_weight_kg(self):
        value = self.cleaned_data['weight_kg']
        if value < 30 or value > 250:
            raise forms.ValidationError('Enter a weight between 30 and 250 kg.')
        return value
