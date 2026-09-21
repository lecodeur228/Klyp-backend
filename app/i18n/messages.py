"""i18n message catalog."""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "ok": "OK",
        "accepted": "Accepted",
        "created": "Created",
        "login_success": "Login successful",
        "logout_success": "Logged out",
        "register_success": "Registration successful",
        "unauthenticated": "Unauthenticated",
        "forbidden": "Forbidden",
        "not_found": "Not found",
        "validation_failed": "Validation failed",
        "invalid_credentials": "Invalid credentials",
        "email_taken": "Email already exists",
        "account_inactive": "Account inactive",
        "health_ok": "Service healthy",
        "health_degraded": "Service degraded",
        "health_unhealthy": "Service unhealthy",
        "ai_generate_success": "Generation completed",
        "ai_job_queued": "AI job queued",
        "file_uploaded": "File uploaded",
    },
    "fr": {
        "ok": "OK",
        "accepted": "Accepté",
        "created": "Créé",
        "login_success": "Connexion réussie",
        "logout_success": "Déconnexion réussie",
        "register_success": "Inscription réussie",
        "unauthenticated": "Non authentifié",
        "forbidden": "Accès refusé",
        "not_found": "Introuvable",
        "validation_failed": "Échec de validation",
        "invalid_credentials": "Identifiants invalides",
        "email_taken": "Cet email existe déjà",
        "account_inactive": "Compte inactif",
        "health_ok": "Service en bonne santé",
        "health_degraded": "Service dégradé",
        "health_unhealthy": "Service indisponible",
        "ai_generate_success": "Génération terminée",
        "ai_job_queued": "Job IA mis en file",
        "file_uploaded": "Fichier téléversé",
    },
}


def translate(key: str, locale: str = "fr") -> str:
    catalog = MESSAGES.get(locale) or MESSAGES["en"]
    return catalog.get(key) or MESSAGES["en"].get(key, key)


def resolve_locale(header: str | None, default: str = "fr") -> str:
    if not header:
        return default
    primary = header.split(",")[0].strip().lower()
    lang = primary.split("-")[0]
    if lang in MESSAGES:
        return lang
    return default
