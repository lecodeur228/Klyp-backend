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
        "project_created": "Project created",
        "project_updated": "Project updated",
        "project_deleted": "Project deleted",
        "video_uploaded": "Video uploaded",
        "video_deleted": "Video deleted",
        "job_cancelled": "Job cancelled",
        "analysis_started": "Analysis started",
        "ai_edit_started": "AI Edit started",
        "edit_plan_updated": "EditPlan updated",
        "captions_started": "Captions generation started",
        "captions_updated": "Captions updated",
        "creative_plan_ready": "Creative plan ready",
        "creative_plan_validated": "Creative plan validated",
        "render_started": "Render started",
        "payment_completed": "Payment completed",
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
        "project_created": "Projet créé",
        "project_updated": "Projet mis à jour",
        "project_deleted": "Projet supprimé",
        "video_uploaded": "Vidéo téléversée",
        "video_deleted": "Vidéo supprimée",
        "job_cancelled": "Job annulé",
        "analysis_started": "Analyse démarrée",
        "ai_edit_started": "AI Edit démarré",
        "edit_plan_updated": "EditPlan mis à jour",
        "captions_started": "Génération des captions démarrée",
        "captions_updated": "Captions mises à jour",
        "creative_plan_ready": "Plan créatif prêt",
        "creative_plan_validated": "Plan créatif validé",
        "render_started": "Rendu démarré",
        "payment_completed": "Paiement effectué",
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
