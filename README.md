# Projet Cloud : réseau social en microservices
 
Application de type réseau social (posts, likes, commentaires, abonnements, fil d'actualité) découpée en microservices Python Flask, conteneurisés avec Docker et destinés à être déployés sur AWS (ECS).
 
## Architecture
 
| Service | Port | Rôle | Base SQLite |
|---|---|---|---|
| **UI** | 5000 | Pages HTML (Flask + Jinja2), appelle les 3 autres services | aucune |
| **USER** | 5001 | Inscription, connexion (JWT), infos et recherche d'utilisateurs | `users` |
| **POST** | 5002 | Posts, likes, commentaires | `posts`, `commentaires`, `likes` |
| **FEED** | 5003 | Abonnements, fil d'actualité, recherche | `abonnements` |
 
Principes :
- Chaque service possède **sa propre base** et n'accède jamais à celle d'un autre.
- Les services communiquent uniquement en **HTTP / JSON**.
- L'authentification repose sur un **token JWT** émis par USER et vérifié par les autres services avec un secret partagé.
```
Navigateur ──► UI ──┬──► USER  (users)
                    ├──► POST  (posts, commentaires, likes)
                    └──► FEED  (abonnements) ──► POST / USER
```
 
## Structure du projet
 
```
projet/
├── README.md
├── docker-compose.yml
├── user/
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
├── post/      (même structure)
├── feed/      (même structure)
└── ui/
    ├── app.py
    ├── requirements.txt
    ├── Dockerfile
    ├── templates/
    └── static/
        ├── css/
        └── js/
```
 
## Variables d'environnement
 
| Variable | Utilisée par | Description |
|---|---|---|
| `JWT_SECRET` | USER, POST, FEED | Secret de signature des tokens. **Même valeur partout.** |
| `DB_PATH` | USER, POST, FEED | Chemin du fichier SQLite (à monter en volume sur ECS) |
| `USER_URL` | UI, FEED | Adresse du service USER |
| `POST_URL` | UI, FEED | Adresse du service POST |
| `FEED_URL` | UI | Adresse du service FEED |
 
En local, des valeurs par défaut existent pour le développement. **Ne jamais les utiliser en production.**
 
## Lancement en local (sans Docker)
 
```bash
cd user
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
python app.py                   # écoute sur le port 5001
```
 
Même principe pour les autres services avec leur port respectif.
 
## Lancement avec Docker
 
```bash
cd user
docker build -t user-service .
docker run -p 5001:5001 -e JWT_SECRET=mon-secret user-service
```
 
## API du service USER (disponible)
 
| Méthode | Route | Corps / paramètres | Réponses |
|---|---|---|---|
| GET | `/health` | | 200 |
| POST | `/register` | JSON : `nom`, `prenom`, `pseudo`, `mdp` | 201, 400, 409 |
| POST | `/login` | JSON : `pseudo`, `mdp` | 200 (token + user), 401 |
| GET | `/users/<id>` | | 200, 404 |
| GET | `/users/search?q=...` | | 200 (liste, 20 max) |
 
### Authentification
 
Après `/login`, le client envoie le token dans l'en-tête :
 
```
Authorization: Bearer <token>
```
 
Pour vérifier un token dans un autre service :
 
```python
payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
user_id = int(payload["sub"])
```
 
## API des autres services (prévue)
 
**POST** : `POST /posts`, `GET /posts?authors=1,2,3`, `POST /posts/<id>/like`, `GET|POST /posts/<id>/comments`
 
**FEED** : `POST /follow/<id>`, `DELETE /follow/<id>`, `GET /feed`, `GET /search?q=...`
 
Chaque service expose aussi `GET /health`.
 
## Déploiement AWS (prévu)
 
1. Création d'un dépôt **ECR** et envoi des images (UI et microservices).
2. Création d'un **cluster ECS** contenant les conteneurs.
3. Cluster adossé à un **Auto Scaling Group (ASG)** et à un **Launch Template** (instances EC2).
4. Chaque service est enregistré dans un **Target Group**, relié à un **Application Load Balancer (ALB)**, puis à l'Internet Gateway.
5. Les routes `/health` servent aux health checks de l'ALB.
6. Infrastructure à décrire ensuite avec **Terraform**.
## Conventions d'équipe
 
- Les champs JSON sont en français et identiques entre tous les services (`pseudo`, `mdp`, `nom`, `prenom`).
- Les erreurs sont renvoyées en JSON : `{"erreur": "message"}`.
- Toute modification d'un endpoint est annoncée à l'équipe : l'UI en dépend.