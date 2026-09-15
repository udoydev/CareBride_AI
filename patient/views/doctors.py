from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import never_cache_auth
from accounts.models import Doctor
from doctors.models import DoctorSchedule


@never_cache_auth
@login_required
@never_cache_auth
@login_required
def doctor_list(request):
    query = request.GET.get("q", "").strip()
    category = (request.GET.get("category") or request.GET.get("specialty") or "").strip()
    district_filter = request.GET.get("district", "").strip()
    sort_by = request.GET.get("sort", "name").strip()

    doctors_qs = Doctor.objects.select_related("user").filter(is_verified=True)

    if query:
        doctors_qs = doctors_qs.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(specialty__icontains=query)
            | Q(hospital_name__icontains=query)
            | Q(clinic_name__icontains=query)
            | Q(user__email__icontains=query)
        )

    if category and category.lower() not in ["all", "সকল ডিপার্টমেন্ট", "সকল ক্যাটাগরি"]:
        doctors_qs = doctors_qs.filter(specialty__icontains=category)

    if district_filter:
        doctors_qs = doctors_qs.filter(user__patient_profile__district=district_filter)

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
