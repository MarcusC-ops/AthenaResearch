from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

from core.models import Organisation
from core.validators import normalise_sg_mobile


class RegistrationForm(forms.Form):
    first_name = forms.CharField(label='First name')
    last_name = forms.CharField(label='Last name')
    email = forms.EmailField(label='Email')
    mobile = forms.CharField(
        label='Mobile number',
        widget=forms.TextInput(attrs={'placeholder': '8 digits, e.g. 91234567'}),
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(
            attrs={'placeholder': 'At least 8 characters'}
        ),
        min_length=8,
    )
    confirm_password = forms.CharField(
        label='Confirm password', widget=forms.PasswordInput
    )
    terms_accepted = forms.BooleanField(
        label='I accept the Terms of use and Privacy policy'
    )

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(username=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean_mobile(self):
        return normalise_sg_mobile(self.cleaned_data['mobile'])

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get('password')
            and cleaned.get('confirm_password')
            and cleaned['password'] != cleaned['confirm_password']
        ):
            self.add_error('confirm_password', 'The two passwords do not match.')
        return cleaned


class ParticipantRegistrationForm(RegistrationForm):
    pass


class ResearcherRegistrationForm(RegistrationForm):
    organisation = forms.ModelChoiceField(
        label='Organisation',
        queryset=Organisation.objects.none(),
        empty_label='Choose your organisation',
    )
    job_title = forms.CharField(
        label='Job title',
        required=False,
        max_length=100,
        widget=forms.TextInput(
            attrs={'placeholder': 'e.g. Clinical research coordinator'}
        ),
    )

    field_order = [
        'first_name', 'last_name', 'organisation', 'job_title', 'email',
        'mobile', 'password', 'confirm_password', 'terms_accepted',
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs['placeholder'] = 'you@organisation.sg'
        self.fields['organisation'].queryset = Organisation.objects.filter(
            is_active=True
        ).order_by('name')
