import os 
import sqlite3
from datetime import datetime, timedelta, timezone

import jwt
from flask import Flask, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "users.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-a-changer")
JWT_DUREE_HEURES = 24

#Base de donnée

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            pseudo TEXT NOT NULL UNIQUE,
            mdp_hash TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

def user_public(row):
    "Renvoi les infos publiques"
    return {
        "id": row["id"],
        "pseudo": row["pseudo"],
        "nom": row["nom"],
        "prenom": row["prenom"],
    }

#Routes

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    nom = (data.get("nom") or "").strip()
    prenom = (data.get("prenom") or "").strip()
    pseudo = (data.get("pseudo") or "").strip()
    mdp = data.get("mdp") or ""

    if not (nom and prenom and pseudo and mdp):
        return jsonify({"erreur": "Tous les champs sont obligatoires"}), 400

    mdp_hash = generate_password_hash(mdp)

    conn = get_db()
    try: 
        cur = conn.execute(
            "INSERT INTO users (nom, prenom, pseudo, mdp_hash) VALUES (?, ?, ?, ?)",
            (nom, prenom, pseudo, mdp_hash),
        )
        conn.commit()
        user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"erreur": "Ce pseudo est déjà utilisé"})
    finally:
        conn.close()

    return jsonify({"id": user_id, "pseudo": pseudo}), 201

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    pseudo = (data.get("pseudo") or "").strip()
    mdp = data.get("mdp") or ""

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE pseudo = ?", (pseudo,)
    ).fetchone()
    conn.close()

    if row is None or not check_password_hash(row["mdp_hash"], mdp):
        return jsonify({"erreur": "Identifiants invalides"}), 401

    payload = { 
        "sub": str(row["id"]),
        "pseudo": row["pseudo"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_DUREE_HEURES),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return jsonify({"token": token, "user": user_public(row)}), 200

@app.route("/users/search")
def search_users():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([]), 200

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM users WHERE pseudo LIKE ? LIMIT 20", (f"%{q}%",)
    ).fetchall()
    conn.close()

    return jsonify([user_public(r) for r in rows]), 200

@app.route("/users/<int:user_id>")
def get_user(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()

    if row is None:
        return jsonify({"erreur": "Utilisateur introuvable"}), 404

    return jsonify(user_public(row)), 200

#Lancement

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
