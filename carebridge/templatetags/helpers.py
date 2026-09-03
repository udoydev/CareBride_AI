from datetime import date
from django.template.defaulttags import register
from accounts.models import SiteSettings


@register.filter
def age(dob):
    if not dob:
        return ""
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


@register.simple_tag
def commission_rate():
    try:
        return SiteSettings.get_solo().platform_commission_rate
    except Exception:
        return 7.50
