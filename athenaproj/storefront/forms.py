from django import forms

from core.models import Study, StudyCategory
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
