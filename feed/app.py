import os
import sqlite3
from functools import wraps

import jwt
import requests
from flask import Flask, g, jsonify, request

app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "feed.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-a-changer")
USER_URL = os.environ.get("USER_URL", "http://localhost:5001")
POST_URL = os.environ.get("POST_URL", "http://localhost:5002")
TIMEOUT = 5

#base de donnée

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS abonnements (
            suiveur_id INTEGER NOT NULL,
            suivi_id INTEGER NOT NULL,
            PRIMARY KEY (suiveur_id, suivi_id),
            CHECK (suiveur_id != suivi_id)
        );

        CREATE INDEX IF NOT EXISTS idx_abonnements_suivi ON abonnements(suivi_id);
        """
    )
    conn.commit()
    conn.close()

def ids_suivis(conn, user_id):
    rows = conn.execute(
        "SELECT suivi_id FROM abonnements WHERE suiveur_id = ?", (user_id,)
    ).fetchall()
    return [r["suivi_id"] for r in rows]

#Authentification

def token_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify({"erreur": "Token manquant"}), 401

        token = header[len("Bearer "):]
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            g.user_id = int(payload["sub"])
            g.pseudo = payload["pseudo"]
        except jwt.ExpiredSignatureError:
            return jsonify({"erreur": "Token expiré"}), 401
        except (jwt.InvalidTokenError, KeyError, ValueError):
            return jsonify({"erreur": "Token invalide"}), 401

        return f(*args, **kwargs)

    return wrapper

#Routes
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/follow/<int:user_id>", methods=["POST", "DELETE"])
@token_required
def follow(user_id):
    if request.method == "POST":
        if user_id == g.user_id:
            return jsonify({"erreur": "Tu ne peux pas t'abonner à toi-même"}), 400

        try:
            r = requests.get(f"{USER_URL}/users/{user_id}", timeout=TIMEOUT)
        except request.RequestException:
            return jsonify({"erreur": "Service USER indisponible"}), 503
        if r.status_code == 404:
            return jsonify({"erreur": "Utilisateur introuvable"}), 404
        if r.status_code != 200:
            return jsonify({"erreur": "Réponse inattendue du service USER"}), 502

    conn = get_db()
    try:
        if request.method == "POST":
            conn.execute(
                "INSERT OR IGNORE INTO abonnements (suiveur_id, suivi_id) VALUES (?, ?)",
                (g.user_id, user_id),
            )
        else:
            conn.execute(
                "DELETE FROM abonnements WHERE suiveur_id = ? AND suivi_id = ?",
                (g.user_id, user_id),
            )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"suivi_id": user_id, "suivi": request.method == "POST"}), 200

@app.route("/following")
@token_required
def following():
    conn = get_db()
    ids = ids_suivis(conn, g.user_id)
    conn.close()
    return jsonify({"ids": ids, "total": len(ids)}), 200

@app.route("/followers")
@token_required
def followers():
    conn = get_db()
    rows = conn.execute(
        "SELECT suiveur_id FROM abonnements WHERE suivi_id = ?", (g.user_id,)
    ).fetchall()
    conn.close()
    ids = [r["suiveur_id"] for r in rows]
    return jsonify({"ids": ids, "total": len(ids)}), 200

@app.route("/feed")
@token_required
def feed():
    try: 
        limit = min(int(request.args.get("limit", 50)), 100)
    except ValueError:
        return jsonify({"erreur": "limite invalide"}), 400

    conn = get_db()
    auteurs = ids_suivis(conn, g.user_id)
    conn.close()
    auteurs.append(g.user_id)

    try:
        r = requests.get(
            f"{POST_URL}/posts",
            params={"authors": ",".join(str(a) for a in auteurs), "limit": limit},
            headers={"Authorization": request.headers["Authorization"]},
            timeout=TIMEOUT,
        )
    except requests.RequestExeception:
        return jsonify({"erreur": "Service POST indisponible"}), 503

    if r.status_code != 200:
        return jsonify({"erreur": "Impmossible de récupérer les posts"}), 502

    return jsonify(r.json()), 200

@app.route("/search")
@token_required
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([]), 200

    try:
        r = requests.get(
            f"{USER_URL}/users/search", params={"q": q}, timeout=TIMEOUT
        )
    except requests.RequestException:
        return jsonify({"erreur": "Service USER indisponible"}), 503

    if r.status_code != 200:
        return jsonify({"erreur": "Recherche impossible"}), 502

    conn = get_db()
    suivis = set(ids_suivis(conn, g.user_id))
    conn.close()

    resultats = []
    for u in r.json():
        if u["id"] == g.user_id:
            continue
        u["suivi_par_moi"] = u["id"] in suivis
        resultats.append(u)

    return jsonify(resultats), 200

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)
