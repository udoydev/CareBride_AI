import re
from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import BD_DISTRICT_CHOICES

FIELD_CLASSES = (
    "w-full rounded-xl border border-stone-300 bg-white px-3.5 py-2.5 text-sm text-stone-900 shadow-2xs "
    "placeholder:text-stone-400 focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500/20 "
    "dark:border-slate-700 dark:bg-slate-800 dark:text-stone-100 dark:placeholder:text-stone-500 "
    "dark:focus:border-teal-400 dark:focus:ring-teal-400/20 transition"
)

FILE_CLASSES = (
    "block w-full rounded-xl border border-dashed border-stone-300 bg-stone-50/50 px-3.5 py-2 text-sm text-stone-800 "
    "file:mr-3.5 file:rounded-full file:border-0 file:bg-teal-600 file:px-4 file:py-1.5 "
    "file:text-xs file:font-bold file:text-white hover:file:bg-teal-700 "
    "dark:border-slate-700 dark:bg-slate-800 dark:text-stone-200 cursor-pointer transition"
)

BD_PHONE_REGEX = re.compile(r"^(?:\+8801|01)[3-9]\d{8}$")


class RegisterForm(forms.Form):
    ROLE_CHOICES = [("patient", "Patient / রোগী"), ("doctor", "Doctor / ডাক্তার")]

    # Step 1: Account Credentials
    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Tanvir / Rahim"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Ahmed / Uddin"}),
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"placeholder": "name@example.com"}),
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={"placeholder": "••••••••"}),
        help_text="Min 8 chars, 1 uppercase, 1 lowercase, 1 number, 1 special character",
    )
    password2 = forms.CharField(
        label="Confirm Password",
        required=True,
        widget=forms.PasswordInput(attrs={"placeholder": "••••••••"}),
    )
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect,
        initial="patient",
    )

    # Step 2: Personal Information
    phone_number = forms.CharField(
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "+8801712345678 or 01712345678"}),
        help_text="Must be a valid Bangladeshi mobile number (013-019)",
    )
    date_of_birth = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Required — Date of birth for age calculation",
    )
    gender = forms.ChoiceField(
        choices=[("Male", "Male"), ("Female", "Female"), ("Other", "Other")],
        required=True,
        initial="Male",
        help_text="Required — Select gender",
    )
    district = forms.ChoiceField(
        choices=BD_DISTRICT_CHOICES,
        initial="Dhaka",
        required=True,
    )

    # Step 3: Patient specific fields
    patient_nid_or_birth_reg = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "NID or Birth Registration No"}),
    )
    patient_identity_doc = forms.FileField(
        required=False,
        help_text="Upload photo/PDF of NID Card, Birth Certificate, or Passport",
    )

    # Step 3: Doctor specific fields
    bmdc_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "BMDC Reg No (e.g. A-12345)"}),
    )
    bmdc_certificate = forms.FileField(
        required=False,
        help_text="Upload BMDC certificate / medical license image or PDF",
    )
    specialty = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g. General Physician, Cardiology"}),
    )
    experience_years = forms.IntegerField(
        min_value=0,
        max_value=60,
        required=False,
        widget=forms.NumberInput(attrs={"placeholder": "e.g. 10", "min": "0", "max": "60"}),
    )
    consultation_fee = forms.DecimalField(
        min_value=0,
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={"placeholder": "e.g. 500", "min": "0", "step": "10"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in ("bmdc_certificate", "patient_identity_doc"):
                field.widget.attrs["class"] = FILE_CLASSES
            elif name != "role":
                field.widget.attrs["class"] = FIELD_CLASSES

        role = None
        if args:
            role = args[0].get("role")
        elif "data" in kwargs:
            role = kwargs["data"].get("role")
        elif "initial" in kwargs:
            role = kwargs["initial"].get("role")

        if role is None:
            role = "patient"

        if role == "patient":
            self.fields["patient_identity_doc"].required = True
            self.fields["bmdc_number"].required = False
            self.fields["bmdc_certificate"].required = False
            self.fields["specialty"].required = False
            self.fields["experience_years"].required = False
            self.fields["consultation_fee"].required = False
        elif role == "doctor":
            self.fields["bmdc_number"].required = False
            self.fields["bmdc_certificate"].required = True
            self.fields["specialty"].required = True
            self.fields["experience_years"].required = True
            self.fields["consultation_fee"].required = True
            self.fields["patient_identity_doc"].required = False

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        email_pattern = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
        if not email_pattern.match(email):
            raise ValidationError("Please enter a valid email address (e.g. user@example.com).")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address already exists. Please log in.")
        return email

    def clean_phone_number(self):
        phone = self.cleaned_data["phone_number"].strip()
        clean_phone = phone.replace(" ", "").replace("-", "")

        if not BD_PHONE_REGEX.match(clean_phone):
            raise ValidationError(
                "Registration is strictly for Bangladeshi residents with a valid BD mobile number (e.g. 01712345678 or +8801712345678)."
            )

        if clean_phone.startswith("01"):
            clean_phone = "+88" + clean_phone

        from accounts.models import Doctor, Patient
        raw_phone = clean_phone.replace("+88", "")
        if (
            User.objects.filter(username=clean_phone).exists()
            or User.objects.filter(username=raw_phone).exists()
            or Patient.objects.filter(phone_number__in=[clean_phone, raw_phone]).exists()
            or Doctor.objects.filter(phone_number__in=[clean_phone, raw_phone]).exists()
        ):
            raise ValidationError("An account with this mobile number already exists. Please log in.")

        return clean_phone

    def clean_first_name(self):
        first_name = self.cleaned_data.get("first_name", "").strip()
        if not first_name:
            raise ValidationError("First name is required.")
        if len(first_name) < 2:
            raise ValidationError("First name must be at least 2 characters.")
        if not re.match(r"^[a-zA-Z\s\.\-'\u0980-\u09FF]+$", first_name):
            raise ValidationError("First name can only contain letters and standard characters.")
        return first_name

    def clean_last_name(self):
        last_name = self.cleaned_data.get("last_name", "").strip()
        if last_name and not re.match(r"^[a-zA-Z\s\.\-'\u0980-\u09FF]+$", last_name):
            raise ValidationError("Last name can only contain letters and standard characters.")
        return last_name or ""

    def clean_password(self):
        password = self.cleaned_data.get("password", "")

        if len(password) < 8:
            raise ValidationError("Password must be at least 8 characters long.")

        if re.search(r"\s", password):
            raise ValidationError("Password cannot contain spaces.")

        if not re.search(r"[A-Z]", password):
            raise ValidationError("Password must contain at least one uppercase letter (A-Z).")

        if not re.search(r"[a-z]", password):
            raise ValidationError("Password must contain at least one lowercase letter (a-z).")

        if not re.search(r"\d", password):
            raise ValidationError("Password must contain at least one number (0-9).")

        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\'\\:"|,.<>\/?`~]', password):
            raise ValidationError("Password must contain at least one special character (!@#$%^&*...).")

        return password

    def clean_password2(self):
        password = self.cleaned_data.get("password")
        password2 = self.cleaned_data.get("password2")

        if password and password2 and password != password2:
            raise ValidationError("Passwords do not match. Please try again.")

        return password2

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")
        if not dob:
            raise ValidationError("Date of birth is required.")
        from django.utils import timezone
        today = timezone.localdate()
        if dob >= today:
            raise ValidationError("Date of birth must be in the past.")
        if dob.year < 1900:
            raise ValidationError("Please enter a valid date of birth (year 1900 or later).")

        role = self.cleaned_data.get("role") or self.data.get("role") or "patient"
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if role == "doctor" and age < 21:
            raise ValidationError("Medical practitioners must be at least 21 years old to register as a doctor.")
        if role == "patient" and age > 125:
            raise ValidationError("Please enter a valid date of birth.")
        return dob

    def clean_patient_nid_or_birth_reg(self):
        nid = self.cleaned_data.get("patient_nid_or_birth_reg", "").strip()
        if nid:
            clean_nid = re.sub(r"[\s-]", "", nid)
            if not clean_nid.isdigit() or len(clean_nid) not in (10, 13, 17):
                raise ValidationError("Bangladeshi NID must be 10, 13, or 17 digits (or 17 digits for birth certificate).")
            return clean_nid
        return ""

    def clean_bmdc_number(self):
        role = self.cleaned_data.get("role") or self.data.get("role")
        bmdc = self.cleaned_data.get("bmdc_number", "").strip()
        if role == "doctor":
            if not bmdc:
                raise ValidationError("BMDC Registration Number is required for doctor registration.")
            clean_bmdc = bmdc.upper().strip()
            from accounts.models import Doctor
            if Doctor.objects.filter(registration_number__iexact=clean_bmdc).exists():
                raise ValidationError("A doctor with this BMDC Registration Number already exists.")
            return clean_bmdc
        return bmdc


class LoginForm(forms.Form):
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(attrs={"placeholder": "your.email@example.com"}),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"placeholder": "••••••••"}),
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        self.user_cache = None
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = FIELD_CLASSES

    def clean(self):
        email = self.cleaned_data.get("email")
        password = self.cleaned_data.get("password")

        if email and password:
            clean_email = email.strip().lower()
            user_exists = User.objects.filter(email__iexact=clean_email).exists()
            if not user_exists:
                raise ValidationError("Invalid email address. No registered account found with this email.")

            self.user_cache = authenticate(
                self.request, email=clean_email, password=password
            )
            if self.user_cache is None:
                raise ValidationError("Wrong password. Please verify your password and try again.")
            elif not self.user_cache.is_active:
                raise ValidationError("This account is inactive. Please contact support.")

        return self.cleaned_data

    def get_user(self):
        return self.user_cache


from django.contrib.admin.forms import AdminAuthenticationForm


class AdminEmailLoginForm(AdminAuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email Address"
        self.fields["username"].widget.attrs["placeholder"] = "name@example.com"

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username and password:
            self.user_cache = authenticate(
                self.request, username=username.strip().lower(), password=password
            )
            if self.user_cache is None:
                raise ValidationError(
                    "Invalid email address or password. Please check your credentials.",
                    code="invalid_login",
                )
            else:
                self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class CareBridgePasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["class"] = FIELD_CLASSES
        self.fields["email"].widget.attrs["placeholder"] = "your.email@example.com"

    def save(self, **kwargs):
        extra = kwargs.get("extra_email_context") or {}
        extra["url_name"] = "accounts:password_reset_confirm"
        kwargs["extra_email_context"] = extra
        return super().save(**kwargs)


class CareBridgeSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = FIELD_CLASSES
            field.widget.attrs["placeholder"] = "••••••••"


class ProfileForm(forms.Form):
    avatar = forms.ImageField(required=False)
    full_name = forms.CharField(max_length=150)
    preferred_language = forms.ChoiceField(
        choices=[("bn", "Bangla"), ("en", "English")],
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["avatar"].widget.attrs["class"] = (
            "block w-full rounded-xl border border-dashed border-stone-300 bg-white px-4 py-3 text-sm "
            "file:mr-4 file:rounded-full file:border-0 file:bg-teal-600 file:px-4 file:py-2 "
            "file:text-sm file:font-semibold file:text-white hover:file:bg-teal-700 "
            "dark:border-slate-700 dark:bg-slate-900 dark:text-stone-100"
        )
        self.fields["full_name"].widget.attrs["class"] = FIELD_CLASSES
