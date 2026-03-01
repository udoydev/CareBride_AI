from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()


class EmailAuthBackend(ModelBackend):
    """
    Custom authentication backend that allows logging in using an email address and password.
    Supports case-insensitive email matching.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = kwargs.get("email") or username
        if not email or not password:
            return None

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Also fallback to username check if email lookup fails
            try:
                user = User.objects.get(username__iexact=email)
            except User.DoesNotExist:
                return None
        except User.MultipleObjectsReturned:
            user = User.objects.filter(email__iexact=email).first()

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
