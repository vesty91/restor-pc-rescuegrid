"""
app/deps.py — Restor-PC RescueGrid
------------------------------------
Ré-exporte les dépendances depuis auth.py pour éviter les imports circulaires.
"""
from .auth import get_user_or_redirect, get_current_user  # noqa: F401
