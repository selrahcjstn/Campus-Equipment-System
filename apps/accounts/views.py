# Create your views here.
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from .forms import LoginForm, RegisterForm
from django.views.decorators.http import require_POST


def register_view(request):
    if request.user.is_authenticated:
        if request.user.role == "ADMIN":
            return redirect("/manage/")
        return redirect("/portal/")

    if request.method == "POST":
        form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("/portal/")
    else:
        form = RegisterForm()

    return render(
        request,
        "accounts/register.html",
        {"form": form}
    )


def login_view(request):
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)

        if form.is_valid():
            user = form.get_user()
            login(request, user)

            if user.role == "ADMIN":
                return redirect("/manage/")

            return redirect("/portal/")

    else:
        form = LoginForm()

    return render(
        request,
        "accounts/login.html",
        {"form": form}
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("/login/")