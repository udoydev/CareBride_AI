from django.urls import path
from . import views

app_name = "prescriptions"

urlpatterns = [
    path("scan/", views.scan_prescription_view, name="scan_prescription"),
    path("<int:prescription_id>/download/", views.printable_prescription_pdf, name="printable_prescription_pdf"),
    path("appointments/<int:appointment_id>/receipt/", views.appointment_receipt_pdf, name="appointment_receipt_pdf"),
    path("bulk-download/", views.bulk_prescriptions_pdf, name="bulk_prescriptions_pdf"),
]
