import os 
import sqlite3
from datetime import datetime, timezone
from functools import wraps

import jwt
from flask import Flask, g, jsonify, request

app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "posts.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-a-changer")
MAX_POST = 500
MAX_COMMENTAIRE = 300

#Base de données

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auteur_id INTEGER NOT NULL,
            auteur_pseudo TEXT NOT NULL,
            texte TEXT,
            image_url TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS commentaires(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pseudo TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS likes (
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (post_id, user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_posts_auteur ON posts(auteur_id);
        CREATE INDEX IF NOT EXISTS idx_commentaires_post ON commentaires(post_id);
        """
    )
    conn.commit()
    conn.close()

def maintenant():
    return datetime.now(timezone.utc).isoformat()

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

#Fonctions utilitaires

POSTS_SELECT = """
    SELECT p.*,
        (SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS nb_likes,
        (SELECT COUNT(*) FROM commentaires c WHERE c.post_id = p.id) AS nb_commentaires,
        EXISTS(SELECT 1 FROM likes l 
            WHERE l.post_id = p.id AND l.user_id = ?) AS like_par_moi
    FROM posts p
"""

def post_to_dict(row):
    return {
        "id": row["id"],
        "auteur_id": row["auteur_id"],
        "auteur_pseudo": row["auteur_pseudo"],
        "texte": row["texte"],
        "image_url": row["image_url"],
        "created_at": row["created_at"],
        "nb_likes": row["nb_likes"],
        "nb_commentaires": row["nb_commentaires"],
        "like_par_moi": bool(row["like_par_moi"]),
    }

def commentaire_to_dict(row):
    return{
        "id": row["id"],
        "post_id": row["post_id"],
        "user_id": row["user_id"],
        "pseudo": row["pseudo_id"],
        "texte": row["texte"],
        "creates_at": row["created_at"],
    }

def get_post(conn, post_id):
    row = conn.execute(
        POSTS_SELECT + " WHERE p.id = ?", (g.user_id, post_id)
    ).fetchone()
    return post_to_dict(row) if row else None

def post_existe(conn, post_id):
    return conn.execute(
        "SELECT 1 FROM posts WHERE id = ?", (post_id,)
    ).fetchone() is not None

#Routes

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/posts", methods=["POST"])
@token_required
def creer_post():
    data = request.get_json(silent=True) or {}
    texte = (data.get("texte") or "").strip()
    image_url = (data.get("image_url") or "").strip()

    if not texte and not image_url:
        return jsonify({"erreur": "Un post doit contenir du texte ou une image"}), 400
    if len(texte) > MAX_POST:
        return jsonify({"erreur": f"Texte trop long ({MAX_POST} caractères max)"}), 400

    conn = get_db()
    try: 
        cur = conn.execute(
            "INSERT INTO posts (auteur_id, auteur_pseudo, texte, image_url, created_at)"
            "VALUES (?, ?, ?, ?, ?)",
            (g.user_id, g.pseudo, texte or None, image_url or None, maintenant()),
        )
        conn.commit()
        post = get_post(conn, cur.lastrowid)
    finally: 
        conn.close()

    return jsonify(post), 201

@app.route("/posts")
@token_required
def lister_posts():
    authors_param = request.args.get("authors")
    try:
        limit = min(int(request.args.get("limit", 50)), 100)
    except ValueError:
        return jsonify({"erreur": "limit invalide"}), 400

    sql = POSTS_SELECT
    params = [g.user_id]

    if authors_param is not None:
        if not authors_param.strip():
            return jsonify([]), 200
        try: 
            authors = [int(a) for a in authors_param.split(",")]
        except ValueError:
            return jsonify({"erreur": "authors doit être une liste d'ids"}), 400

        sql += "ORDER BY p.created_at DESC, p.id DESC LIMIT ?"
        params.append(limit)

        conn = get_db()
        rows = conn.execute(sql, params).fetchall()
        conn.close()

        return jsonify([post_to_dict(r) for r in rows]), 200

@app.route("/posts/<int:post_id>")
@token_required
def lire_post(post_id):
    conn = get_db()
    post = get_post(conn, post_id)
    conn.close()

    if post is None:
        return jsonify({"erreur": "Post introuvable"}), 404
    return jsonify(post), 200

@app.route("/posts/<int:post_id>/like", methods=["POST", "DELETE"])
@token_required
def like(post_id):
    conn = get_db()
    try:
        if not post_existe(conn, post_id):
            return jsonify({"erreur": "Post introuvable"}), 404

        if request.method == "POST":
            conn.execute(
                "INSERT OR IGNORE INTO likes (post_id, user_id) VALUES (?, ?)",
                (post_id, g.user_id),
            )
        else:
            conn.execute(
                "DELETE FROM likes WHERE post_id = ? AND user_id = ?",
                (post_id, g.user_id),
            )
        conn.commit()
        nb = conn.execute(
            "SELECT COUNT(*) FROM likes WHERE post_id = ?", (post_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    return jsonify({
        "post_id": post_id,
        "nb_likes": nb,
        "like_par_moi": request.method == "POST",
    }), 200

@app.route("/posts/<int:post_id>/comments")
@token_required
def lister_commentaires(post_id):
    conn = get_db()
    try: 
        if not post_existe(conn, post_id):
            return jsonify({"erreur": "Post introuvable"}), 404
        rows = conn.execute(
            "SELECT * FROM commentaires WHERE post_id = ? ORDER BY created_at ASC, id ASC",
            (post_id,),
        ).fetchall()
    finally:
        conn.close()

    return jsonify([commentaire_to_dict(r) for r in rows]), 200

@app.route("/posts/<int:post_id>/comments", methods=["POST"])
@token_required
def ajouter_commentaire(post_id):
    data = request.get_json(silent=True) or {}
    texte = (data.get("texte") or "").strip()

    if not texte:
        return jsonify({"erreur": "Le commentaire est vide"}), 400
    if len(texte) > MAX_COMMENTAIRE:
        return jsonify({"erreur": f"Commentaire trop long ({MAX_COMMENTAIRE} max)"}), 400

    conn = get_db()
    try:
        if not post_existe(conn, post_id):
            return jsonify({"erreur": "Post introuvable"}), 404
        cur = conn.execute(
            "INSERT INTO commentaires (post_id, user_id, pseudo, texte, created_at)"
            "VALUES (?, ?, ?, ?, ?)",
            (post_id, g.user_id, g.pseudo, texte, maintenant()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM commentaires WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    finally:
        conn.close()

    return jsonify(commentaire_to_dict(row)), 201

#lancement

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
