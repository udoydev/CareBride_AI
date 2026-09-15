from .appointments import (
    _auto_detect_missed_for_doctor,
    _auto_mark_missed_today,
    appointment_detail,
    appointment_list,
    appointment_report,
    appointment_report_export,
    approve_cancellation,
    auto_detect_missed,
    mark_attendance,
    reports,
    verify_payment,
)
from .dashboard import (
    dashboard,
    notifications,
)
from .financials import (
    doctor_financial_report,
)
from .patients import (
    patient_detail,
    patient_list,
)
from .prescriptions import (
    create_prescription,
    download_prescription,
    edit_prescription,
    history,
    prescription_detail,
    update_followup_status,
)
from .profile import (
    delete_schedule,
    profile_edit,
    schedule_management,
)

__all__ = [
    "dashboard",
    "notifications",
    "patient_list",
    "patient_detail",
    "create_prescription",
    "edit_prescription",
    "prescription_detail",
    "download_prescription",
    "update_followup_status",
    "history",
    "profile_edit",
    "schedule_management",
    "delete_schedule",
    "doctor_financial_report",
    "appointment_list",
    "appointment_detail",
    "approve_cancellation",
    "mark_attendance",
    "auto_detect_missed",
    "appointment_report",
    "appointment_report_export",
    "reports",
    "verify_payment",
    "_auto_detect_missed_for_doctor",
    "_auto_mark_missed_today",
]
