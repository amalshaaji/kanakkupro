from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.tenants.models import PilotFeedback
from apps.tenants.pilot import (
    confirm_check,
    pilot_progress,
    require_pilot_access,
    submit_feedback,
    update_feedback,
)
from apps.tenants.pilot_forms import PilotCheckForm, PilotFeedbackForm, PilotStatusForm


@login_required
@require_http_methods(["GET", "POST"])
def pilot_guide(request):
    require_pilot_access(request.tenant, request.user)
    feedback_form = PilotFeedbackForm()
    status = 200
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "check":
            form = PilotCheckForm(request.POST)
            if not form.is_valid():
                return HttpResponseBadRequest("Invalid pilot check.")
            confirm_check(
                tenant=request.tenant,
                actor=request.user,
                **form.cleaned_data,
                request_id=request.request_id,
            )
            messages.success(request, "Your business check was updated.")
            return redirect("dashboard:pilot")
        if action != "feedback":
            return HttpResponseBadRequest("Choose a valid action.")
        feedback_form = PilotFeedbackForm(request.POST)
        if feedback_form.is_valid():
            submit_feedback(
                tenant=request.tenant,
                actor=request.user,
                values=feedback_form.cleaned_data,
                request_id=request.request_id,
            )
            messages.success(
                request,
                "Feedback saved for your business. "
                "This does not send a support message.",
            )
            return redirect("dashboard:pilot")
        status = 400
    context = pilot_progress(request.tenant, request.user)
    context.update(
        {
            "feedback_form": feedback_form,
            "feedback": Paginator(
                PilotFeedback.objects.filter(tenant=request.tenant).select_related(
                    "submitted_by"
                ),
                25,
            ).get_page(request.GET.get("page")),
            "status_choices": PilotFeedback.Status.choices,
        }
    )
    return render(request, "tenants/pilot.html", context, status=status)


@login_required
@require_POST
def feedback_status(request, feedback_id):
    require_pilot_access(request.tenant, request.user)
    form = PilotStatusForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Choose a valid status.")
    update_feedback(
        tenant=request.tenant,
        actor=request.user,
        feedback_id=feedback_id,
        status=form.cleaned_data["status"],
        request_id=request.request_id,
    )
    return redirect("dashboard:pilot")
