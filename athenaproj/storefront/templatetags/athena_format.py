from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def money(value):
    amount = Decimal(value)
    if amount == amount.to_integral_value():
        return f'${amount:,.0f}'
    return f'${amount:,.2f}'


@register.filter
def money_cents(value):
    return f'S${value:,.2f}'


@register.simple_tag(takes_context=True)
def page_url(context, page):
    query = context['request'].GET.copy()
    query['page'] = page
    return mark_safe(f'?{query.urlencode()}')
