"""Paramètres, utilisateurs et journal d'activité."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import (
    get_admin_or_redirect,
    get_user_or_redirect,
    hash_password,
    log_activity,
    validate_password_strength,
    verify_password,
)
from ..database import get_session
from ..models import ActivityLog, User
from ..services.mail import send_document_email

router = APIRouter()
_templates: Jinja2Templates | None = None


def init_router(templates: Jinja2Templates) -> APIRouter:
    global _templates
    _templates = templates
    return router


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    return _templates.TemplateResponse(
        "settings.html",
        {"active_page": "settings", "request": request, "user": user, "message": None, "error": None},
    )


@router.post("/settings/email-test")
def settings_email_test(
    request: Request,
    test_email: str = Form(...),
    session: Session = Depends(get_session),
):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    html_test = "<h1>Test email RESTOR-PC</h1><p>Configuration SMTP Infomaniak opérationnelle.</p>"
    ok, detail = send_document_email(
        to_email=test_email.strip(),
        subject="Test email RESTOR-PC",
        body="Bonjour, ceci est un test d'envoi email depuis Restor-PC RescueGrid.",
        html_attachment=html_test,
        attachment_name="test-restor-pc.pdf",
    )
    if ok:
        log_activity(session, user, "settings.email_test", test_email.strip())
        session.commit()
        return _templates.TemplateResponse("settings.html", {
            "active_page": "settings",
            "request": request,
            "user": user,
            "message": f"Email de test envoyé à {test_email.strip()} ({detail}).",
            "error": None,
        })
    return _templates.TemplateResponse("settings.html", {
        "active_page": "settings",
        "request": request,
        "user": user,
        "message": None,
        "error": f"Erreur email : {detail}. Vérifie MAIL_PASSWORD dans .env.",
    })


@router.post("/settings/password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    if new_password != confirm_password:
        return _templates.TemplateResponse("settings.html", {
            "active_page": "settings",
            "request": request,
            "user": user,
            "message": None,
            "error": "Les mots de passe ne correspondent pas.",
        })
    password_error = validate_password_strength(new_password, user.username)
    if password_error:
        return _templates.TemplateResponse("settings.html", {
            "active_page": "settings",
            "request": request,
            "user": user,
            "message": None,
            "error": password_error,
        })
    if not verify_password(current_password, user.hashed_password):
        return _templates.TemplateResponse("settings.html", {
            "active_page": "settings",
            "request": request,
            "user": user,
            "message": None,
            "error": "Mot de passe actuel incorrect.",
        })
    user.hashed_password = hash_password(new_password)
    log_activity(session, user, "settings.password", user.username)
    session.commit()
    return _templates.TemplateResponse("settings.html", {
        "active_page": "settings",
        "request": request,
        "user": user,
        "message": "Mot de passe mis à jour.",
        "error": None,
    })


@router.post("/settings/2fa-reset")
def reset_two_fa(
    request: Request,
    current_password: str = Form(...),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    if not verify_password(current_password, user.hashed_password):
        return _templates.TemplateResponse("settings.html", {
            "active_page": "settings",
            "request": request,
            "user": user,
            "message": None,
            "error": "Mot de passe actuel incorrect.",
        })
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_recovery_codes = None
    log_activity(session, user, "2fa.reset", user.username)
    session.commit()
    return _templates.TemplateResponse("settings.html", {
        "active_page": "settings",
        "request": request,
        "user": user,
        "message": "2FA réinitialisée — un nouvel enrôlement sera demandé à la prochaine connexion.",
        "error": None,
    })


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, session: Session = Depends(get_session)):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    users = session.scalars(select(User).order_by(User.created_at.desc())).all()
    return _templates.TemplateResponse(
        "users.html",
        {"active_page": "users", "request": request, "users": users, "user": user, "error": None},
    )


@router.post("/users")
def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    role: str = Form("technicien"),
    session: Session = Depends(get_session),
):
    admin, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    if session.scalars(select(User).where(User.username == username)).first():
        users = session.scalars(select(User).order_by(User.created_at.desc())).all()
        return _templates.TemplateResponse("users.html", {
            "active_page": "users",
            "request": request,
            "users": users,
            "user": admin,
            "error": "Identifiant déjà utilisé.",
        })
    password_error = validate_password_strength(password, username)
    if password_error:
        users = session.scalars(select(User).order_by(User.created_at.desc())).all()
        return _templates.TemplateResponse("users.html", {
            "active_page": "users",
            "request": request,
            "users": users,
            "user": admin,
            "error": password_error,
        })
    if role not in {"admin", "technicien"}:
        role = "technicien"
    session.add(User(
        username=username.strip(),
        hashed_password=hash_password(password),
        full_name=full_name or None,
        role=role,
    ))
    log_activity(session, admin, "user.create", username)
    session.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/delete/user/{user_id}")
def delete_user(user_id: int, request: Request, session: Session = Depends(get_session)):
    admin, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    target = session.scalars(select(User).where(User.id == user_id)).first()
    if target and target.id != admin.id:
        session.delete(target)
        log_activity(session, admin, "user.delete", target.username)
        session.commit()
    return RedirectResponse("/users", status_code=303)


@router.get("/activity", response_class=HTMLResponse)
def activity_page(request: Request, session: Session = Depends(get_session)):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    logs = session.scalars(select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(200)).all()
    return _templates.TemplateResponse(
        "activity.html",
        {"active_page": "activity", "request": request, "logs": logs, "user": user},
    )
