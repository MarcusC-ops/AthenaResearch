from django import template

register = template.Library()


@register.filter
def suppress_small(value):
    """Show 'fewer than 5' for 1-4, actual number for 5+, and 0 for zero."""
    try:
        num = int(value)
        if num == 0:
            return '0'
        elif 1 <= num <= 4:
            return 'fewer than 5'
        else:
            return str(num)
    except (ValueError, TypeError):
        return str(value)


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary."""
    if dictionary is None:
        return None
    return dictionary.get(key, 0)
