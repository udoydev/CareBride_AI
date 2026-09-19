from django.urls import path
from . import views

app_name = "prescriptions"

urlpatterns = [
    path("scan/", views.scan_prescription_view, name="scan_prescription"),
    path("scan/scanner/", views.scan_prescription_view, name="scan"),
    path("<int:prescription_id>/view/", views.view_prescription_online, name="view_prescription_online"),
    path("<int:prescription_id>/download/", views.printable_prescription_pdf, name="printable_prescription_pdf"),
    path("appointments/<int:appointment_id>/receipt/", views.appointment_receipt_pdf, name="appointment_receipt_pdf"),
    path("appointments/<int:appointment_id>/refund/", views.refund_receipt_pdf, name="refund_receipt_pdf"),
    path("bulk-download/", views.bulk_prescriptions_pdf, name="bulk_prescriptions_pdf"),
]
