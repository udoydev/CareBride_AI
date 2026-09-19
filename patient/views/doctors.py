import re
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Value
from django.db.models.functions import Concat
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import never_cache_auth
from accounts.models import Doctor
from doctors.models import DoctorSchedule


@never_cache_auth
@login_required
def doctor_list(request):
    query = request.GET.get("q", "").strip()
    clean_query = re.sub(r'^(?:Dr\.?\s*|Doctor\s*)+', '', query, flags=re.IGNORECASE).strip()
    category = (request.GET.get("category") or request.GET.get("specialty") or "").strip()
    district_filter = request.GET.get("district", "").strip()
    sort_by = request.GET.get("sort", "name").strip()

    doctors_qs = Doctor.objects.select_related("user").filter(is_verified=True).annotate(
        full_name_clean=Concat('user__first_name', Value(' '), 'user__last_name'),
        full_name_dr=Concat(Value('Dr. '), 'user__first_name', Value(' '), 'user__last_name')
    )

    if query:
        doctors_qs = doctors_qs.filter(
            Q(full_name_clean__icontains=clean_query if clean_query else query)
            | Q(full_name_dr__icontains=query)
            | Q(user__first_name__icontains=clean_query if clean_query else query)
            | Q(user__last_name__icontains=clean_query if clean_query else query)
            | Q(user__email__icontains=query)
            | Q(specialty__icontains=query)
            | Q(clinic_name__icontains=query)
            | Q(location_text__icontains=query)
            | Q(designation__icontains=query)
            | Q(degrees__icontains=query)
            | Q(bio__icontains=query)
        )

    if category and category.lower() not in ["all", "সকল ডিপার্টমেন্ট", "সকল ক্যাটাগরি", "all departments"]:
        doctors_qs = doctors_qs.filter(specialty__icontains=category)

    if district_filter:
        doctors_qs = doctors_qs.filter(
            Q(location_text__icontains=district_filter)
            | Q(clinic_name__icontains=district_filter)
        )

    if sort_by == "experience":
        doctors_qs = doctors_qs.order_by("-experience_years")
    elif sort_by == "fee_asc":
        doctors_qs = doctors_qs.order_by("consultation_fee")
    elif sort_by == "fee_desc":
        doctors_qs = doctors_qs.order_by("-consultation_fee")
    else:
        doctors_qs = doctors_qs.order_by("user__first_name", "user__last_name")

    paginator = Paginator(doctors_qs, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    raw_specs = Doctor.objects.filter(is_verified=True).values_list("specialty", flat=True).distinct()
    categories_list = ["All"]
    for spec in raw_specs:
        if spec and spec.strip():
            for s in spec.split(","):
                clean_s = s.strip()
                if clean_s and clean_s not in categories_list:
                    categories_list.append(clean_s)

    categories_list[1:] = sorted(categories_list[1:])

    suggested_doctors = Doctor.objects.filter(is_verified=True).order_by("-experience_years")[:4]

    return render(
        request,
        "patient/doctor_list.html",
        {
            "doctors": page_obj,
            "page_obj": page_obj,
            "query": query,
            "category": category or "All",
            "specialty_filter": category,
            "categories": categories_list,
            "suggested": suggested_doctors,
            "suggested_doctors": suggested_doctors,
            "district_filter": district_filter,
            "sort_by": sort_by,
        },
    )


@never_cache_auth
@login_required
def doctor_detail(request, doctor_id):
    doctor = get_object_or_404(Doctor, pk=doctor_id)
    schedules = DoctorSchedule.objects.filter(doctor=doctor, is_active=True).order_by("day_of_week", "start_time")

    return render(
        request,
        "patient/doctor_detail.html",
        {
            "doctor": doctor,
            "schedules": schedules,
        },
    )
