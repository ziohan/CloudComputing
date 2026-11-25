"""Service UI : pages HTML (Flask + Jinja2) qui consomment les services USER, POST et FEED."""
import os
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

import requests
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-ui-a-changer")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24),  # = durée de vie du token JWT
)

USER_URL = os.environ.get("USER_URL", "http://localhost:5001").rstrip("/")
POST_URL = os.environ.get("POST_URL", "http://localhost:5002").rstrip("/")
FEED_URL = os.environ.get("FEED_URL", "http://localhost:5003").rstrip("/")
TIMEOUT = 5  # secondes

NOMS_SERVICES = {USER_URL: "USER", POST_URL: "POST", FEED_URL: "FEED"}

# Mêmes limites que le service POST
MAX_POST = 500
MAX_COMMENTAIRE = 300
MDP_MIN = 8


# ---------- Erreurs liées aux autres services ----------

class ServiceError(Exception):
    """Un microservice est injoignable ou a renvoyé une réponse inattendue."""


class AuthError(Exception):
    """Token absent, invalide ou expiré : il faut se reconnecter."""


# ---------- Appels aux microservices ----------

def appel(methode, base, chemin, *, json=None, params=None, auth=True):
    """Appelle un microservice et renvoie (code_http, corps_json).

    - panne réseau ou erreur 5xx  -> ServiceError (page 503)
    - 401 sur une route protégée  -> AuthError (retour à la connexion)
    - 4xx métier (400, 404, 409)  -> renvoyés à la route, qui décide quoi afficher
    """
    headers = {}
    if auth and session.get("token"):
        headers["Authorization"] = f"Bearer {session['token']}"

    try:
        r = requests.request(
            methode,
            f"{base}{chemin}",
            json=json,
            params=params,
            headers=headers,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        nom = NOMS_SERVICES.get(base, base)
        app.logger.warning("Appel %s %s%s impossible : %s", methode, base, chemin, exc)
        raise ServiceError(
            f"Le service {nom} est injoignable. Vérifie qu'il est lancé, puis réessaie."
        )

    try:
        corps = r.json()
    except ValueError:
        corps = None

    if r.status_code == 401 and auth:
        raise AuthError()
    if r.status_code >= 500:
        nom = NOMS_SERVICES.get(base, base)
        detail = message_erreur(corps, "")
        app.logger.warning(
            "Appel %s %s%s -> %s %s", methode, base, chemin, r.status_code, detail
        )
        message = f"Le service {nom} a répondu avec l'erreur {r.status_code}"
        message += f" ({detail})." if detail else "."
        raise ServiceError(message)

    return r.status_code, corps


def message_erreur(corps, defaut):
    if isinstance(corps, dict) and corps.get("erreur"):
        return corps["erreur"]
    return defaut


def total(corps):
    return corps.get("total", 0) if isinstance(corps, dict) else 0


def safe_next(cible):
    """N'accepte que des chemins internes (évite les redirections vers un autre site)."""
    if cible and cible.startswith("/") and not cible.startswith("//") and "\\" not in cible:
        return cible
    return None


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "token" not in session:
            flash("Connecte-toi pour accéder à cette page.", "info")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)

    return wrapper


# ---------- Jinja ----------

@app.template_filter("datefr")
def datefr(valeur):
    try:
        d = datetime.fromisoformat(valeur)
    except (TypeError, ValueError):
        return ""
    try:
        d = d.astimezone(ZoneInfo("Europe/Paris"))
    except Exception:
        pass
    return d.strftime("%d/%m/%Y à %H:%M")


@app.context_processor
def contexte():
    return {
        "current_url": request.full_path.rstrip("?"),
        "MAX_POST": MAX_POST,
        "MAX_COMMENTAIRE": MAX_COMMENTAIRE,
        "MDP_MIN": MDP_MIN,
    }


# ---------- Pages publiques ----------

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/")
def index():
    if "token" in session:
        return redirect(url_for("feed"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "token" in session:
        return redirect(url_for("feed"))
    if request.method == "GET":
        return render_template("register.html", form={})

    form = {k: request.form.get(k, "").strip() for k in ("nom", "prenom", "pseudo")}
    mdp = request.form.get("mdp", "")
    mdp2 = request.form.get("mdp2", "")

    erreur = None
    if not all(form.values()) or not mdp:
        erreur = "Tous les champs sont obligatoires."
    elif len(mdp) < MDP_MIN:
        erreur = f"Le mot de passe doit faire au moins {MDP_MIN} caractères."
    elif mdp != mdp2:
        erreur = "Les mots de passe ne correspondent pas."
    if erreur:
        flash(erreur, "error")
        return render_template("register.html", form=form), 400

    status, corps = appel(
        "POST", USER_URL, "/register", json={**form, "mdp": mdp}, auth=False
    )
    if status == 201:
        flash("Compte créé ! Tu peux maintenant te connecter.", "success")
        return redirect(url_for("login"))

    flash(message_erreur(corps, "Inscription impossible."), "error")
    return render_template("register.html", form=form), (409 if status == 409 else 400)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "token" in session:
        return redirect(url_for("feed"))
    if request.method == "GET":
        return render_template("login.html")

    pseudo = request.form.get("pseudo", "").strip()
    mdp = request.form.get("mdp", "")
    if not pseudo or not mdp:
        flash("Renseigne ton pseudo et ton mot de passe.", "error")
        return render_template("login.html"), 400

    status, corps = appel(
        "POST", USER_URL, "/login", json={"pseudo": pseudo, "mdp": mdp}, auth=False
    )
    if status == 200 and isinstance(corps, dict) and "token" in corps:
        session.clear()
        session.permanent = True
        session["token"] = corps["token"]
        session["user_id"] = corps["user"]["id"]
        session["pseudo"] = corps["user"]["pseudo"]
        return redirect(safe_next(request.args.get("next")) or url_for("feed"))

    flash(message_erreur(corps, "Connexion impossible."), "error")
    return render_template("login.html"), (401 if status == 401 else 400)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Tu es déconnecté.", "info")
    return redirect(url_for("index"))


# ---------- Fil d'actualité et posts ----------

@app.route("/feed")
@login_required
def feed():
    status, corps = appel("GET", FEED_URL, "/feed")
    if status == 200 and isinstance(corps, list):
        posts = corps
    else:
        posts = []
        flash(message_erreur(corps, "Impossible de charger le fil d'actualité."), "error")
    return render_template("feed.html", posts=posts)


@app.route("/posts/new", methods=["POST"])
@login_required
def nouveau_post():
    texte = request.form.get("texte", "").strip()
    image_url = request.form.get("image_url", "").strip()

    if not texte and not image_url:
        flash("Écris quelque chose ou ajoute une image.", "error")
    elif len(texte) > MAX_POST:
        flash(f"Ton post est trop long ({MAX_POST} caractères max).", "error")
    elif image_url and not image_url.startswith(("http://", "https://")):
        flash("L'adresse de l'image doit commencer par http:// ou https://.", "error")
    else:
        status, corps = appel(
            "POST", POST_URL, "/posts", json={"texte": texte, "image_url": image_url}
        )
        if status == 201:
            flash("Post publié.", "success")
        else:
            flash(message_erreur(corps, "Impossible de publier le post."), "error")

    return redirect(safe_next(request.form.get("next")) or url_for("feed"))


@app.route("/post/<int:post_id>")
@login_required
def post_detail(post_id):
    status, post = appel("GET", POST_URL, f"/posts/{post_id}")
    if status == 404:
        abort(404)
    if status != 200 or not isinstance(post, dict):
        raise ServiceError("Impossible de charger ce post.")

    status, commentaires = appel("GET", POST_URL, f"/posts/{post_id}/comments")
    if status != 200 or not isinstance(commentaires, list):
        commentaires = []
        flash("Impossible de charger les commentaires.", "error")

    return render_template("post_detail.html", post=post, commentaires=commentaires)


@app.route("/post/<int:post_id>/like", methods=["POST"])
@login_required
def liker(post_id):
    deja_like = request.form.get("liked") == "1"
    methode = "DELETE" if deja_like else "POST"
    status, corps = appel(methode, POST_URL, f"/posts/{post_id}/like")
    if status == 404:
        flash("Ce post n'existe plus.", "error")
    elif status != 200:
        flash(message_erreur(corps, "Impossible de modifier le like."), "error")

    cible = safe_next(request.form.get("next")) or url_for("post_detail", post_id=post_id)
    return redirect(f"{cible.split('#')[0]}#post-{post_id}")


@app.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
def commenter(post_id):
    texte = request.form.get("texte", "").strip()
    if not texte:
        flash("Le commentaire est vide.", "error")
    elif len(texte) > MAX_COMMENTAIRE:
        flash(f"Commentaire trop long ({MAX_COMMENTAIRE} caractères max).", "error")
    else:
        status, corps = appel(
            "POST", POST_URL, f"/posts/{post_id}/comments", json={"texte": texte}
        )
        if status == 201:
            flash("Commentaire ajouté.", "success")
        elif status == 404:
            flash("Ce post n'existe plus.", "error")
        else:
            flash(message_erreur(corps, "Impossible d'ajouter le commentaire."), "error")

    return redirect(url_for("post_detail", post_id=post_id))


# ---------- Recherche et abonnements ----------

@app.route("/search")
@login_required
def rechercher():
    q = request.args.get("q", "").strip()
    resultats = []
    if q:
        status, corps = appel("GET", FEED_URL, "/search", params={"q": q})
        if status == 200 and isinstance(corps, list):
            resultats = corps
        else:
            flash(message_erreur(corps, "La recherche a échoué."), "error")
    return render_template("search.html", q=q, resultats=resultats)


@app.route("/follow/<int:user_id>", methods=["POST"])
@login_required
def suivre(user_id):
    se_desabonner = request.form.get("action") == "unfollow"
    methode = "DELETE" if se_desabonner else "POST"
    status, corps = appel(methode, FEED_URL, f"/follow/{user_id}")
    if status == 200:
        flash("Abonnement supprimé." if se_desabonner else "Abonnement ajouté.", "success")
    else:
        flash(message_erreur(corps, "Action impossible."), "error")
    return redirect(safe_next(request.form.get("next")) or url_for("feed"))


# ---------- Profils ----------

@app.route("/profile")
@login_required
def profile():
    uid = session["user_id"]

    status, user = appel("GET", USER_URL, f"/users/{uid}", auth=False)
    if status != 200 or not isinstance(user, dict):
        user = {"id": uid, "pseudo": session.get("pseudo", ""), "nom": "", "prenom": ""}

    _, following = appel("GET", FEED_URL, "/following")
    _, followers = appel("GET", FEED_URL, "/followers")

    status, posts = appel("GET", POST_URL, "/posts", params={"authors": uid})
    if status != 200 or not isinstance(posts, list):
        posts = []

    return render_template(
        "profile.html",
        user=user,
        nb_abonnements=total(following),
        nb_abonnes=total(followers),
        posts=posts,
    )


@app.route("/user/<int:user_id>")
@login_required
def user_page(user_id):
    if user_id == session["user_id"]:
        return redirect(url_for("profile"))

    status, user = appel("GET", USER_URL, f"/users/{user_id}", auth=False)
    if status == 404:
        abort(404)
    if status != 200 or not isinstance(user, dict):
        raise ServiceError("Impossible de charger ce profil.")

    status, following = appel("GET", FEED_URL, "/following")
    suivi = (
        status == 200 and isinstance(following, dict) and user_id in following.get("ids", [])
    )

    status, posts = appel("GET", POST_URL, "/posts", params={"authors": user_id})
    if status != 200 or not isinstance(posts, list):
        posts = []

    return render_template("user.html", user=user, suivi=suivi, posts=posts)


# ---------- Gestion des erreurs ----------

@app.errorhandler(404)
def page_introuvable(e):
    return render_template("404.html"), 404


@app.errorhandler(ServiceError)
def service_indisponible(e):
    return render_template("erreur.html", message=str(e)), 503


@app.errorhandler(AuthError)
def session_expiree(e):
    session.clear()
    flash("Ta session a expiré, reconnecte-toi.", "info")
    return redirect(url_for("login"))


@app.errorhandler(500)
def erreur_interne(e):
    return render_template("erreur.html", message="Une erreur inattendue est survenue."), 500


# ---------- Lancement ----------

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
    )