from django import template
from leaves.bs_convert import ad_to_bs_display

register = template.Library()


@register.filter
def to_bs(value, include_year=True):
    try:
        d = value.date() if hasattr(value, 'date') else value
        return ad_to_bs_display(d, include_year=bool(include_year))
    except (ValueError, AttributeError):
        return value


@register.filter
def to_bs_short(value):
    try:
        d = value.date() if hasattr(value, 'date') else value
        return ad_to_bs_display(d, include_year=False)
    except (ValueError, AttributeError):
        return value