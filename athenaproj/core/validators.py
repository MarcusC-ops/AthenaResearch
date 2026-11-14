"""Shared validators."""

from django.core.exceptions import ValidationError


def normalise_sg_mobile(value):
    mobile = str(value).replace(' ', '')
    if mobile.startswith('+65'):
        mobile = mobile[3:]
    elif mobile.startswith('65'):
        mobile = mobile[2:]
    if len(mobile) != 8 or mobile[0] not in '89' or not mobile.isdigit():
        raise ValidationError(
            'Enter a Singapore mobile number, for example 9123 4567.'
        )
    return f'+65{mobile}'
