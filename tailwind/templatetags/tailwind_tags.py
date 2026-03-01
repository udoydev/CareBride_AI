from django import template


register = template.Library()


@register.simple_tag
def tailwind_css():
    """Return no-op CSS markup.

    The project already loads Tailwind from the CDN in base.html, so this
    tag only needs to exist to keep older templates from failing to load.
    """

    return ""

