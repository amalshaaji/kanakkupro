from django.urls import path

from apps.payments import views

app_name = "payments"
urlpatterns = [
    path("invoice/<uuid:invoice_id>/record/", views.record, name="record"),
    path("<uuid:payment_id>/reverse/", views.reverse, name="reverse"),
]
