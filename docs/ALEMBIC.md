# Guide Alembic — Restor-PC RescueGrid v12.2

## Pourquoi Alembic ?

L'ancien système (`_add_column_if_missing` dans `database.py`) était fragile :
- Impossible de faire un **rollback** (annuler une migration)
- Aucune traçabilité des changements de schéma
- Ne fonctionnait pas sur PostgreSQL en production
- Pas de gestion des colonnes renommées ou supprimées

Alembic résout tout ça proprement.

---

## Installation

```bash
cd backend/
pip install alembic
```

---

## Commandes du quotidien

### Appliquer toutes les migrations (démarrage serveur / déploiement)
```bash
cd backend/
alembic upgrade head
```

### Voir où on en est
```bash
alembic current          # révision appliquée
alembic history          # liste complète des migrations
```

### Créer une nouvelle migration après avoir modifié models.py
```bash
alembic revision --autogenerate -m "ajout colonne email_verified sur user"
```
Alembic compare `models.py` avec l'état réel de la BDD et génère le fichier automatiquement.
Vérifiez toujours le fichier généré dans `alembic/versions/` avant de l'appliquer.

### Appliquer la nouvelle migration
```bash
alembic upgrade head
```

### Annuler la dernière migration
```bash
alembic downgrade -1
```

### Annuler toutes les migrations (reset complet)
```bash
alembic downgrade base
```

---

## Flux de travail standard pour ajouter une colonne

**Avant (ancien système) :**
```python
# database.py
_add_column_if_missing(conn, "client", "siret", "ALTER TABLE client ADD COLUMN siret VARCHAR(20)")
```

**Maintenant (Alembic) :**

1. Modifier `models.py` :
```python
class Client(Base):
    # ...
    siret: Mapped[str | None] = mapped_column(String(20), nullable=True)
```

2. Générer la migration :
```bash
alembic revision --autogenerate -m "ajout siret client"
```

3. Appliquer :
```bash
alembic upgrade head
```

C'est tout. Alembic détecte la différence et génère le bon SQL, que vous soyez sur SQLite ou PostgreSQL.

---

## SQLite vs PostgreSQL

`env.py` active automatiquement `render_as_batch=True` pour SQLite.
SQLite ne supporte pas `ALTER TABLE ADD COLUMN` complexe — Alembic contourne ça
en recréant la table entière en arrière-plan, de façon transparente.

Sur PostgreSQL, les migrations classiques sont générées directement.

---

## Première installation (nouvelle BDD)

```bash
cd backend/
alembic upgrade head   # crée toutes les tables + enregistre la révision
uvicorn app.main:app   # démarre le serveur
```

## Migration depuis une BDD existante (v11/v12.1)

Si vous avez une BDD existante créée par l'ancien système (`rescuegrid.db`),
le serveur détecte au démarrage que les tables existent déjà et stampe
automatiquement Alembic à `head` — vos données sont préservées.

```bash
# Vérification manuelle si besoin :
alembic stamp head
alembic current   # doit afficher la dernière révision
```

---

## Structure des fichiers

```
backend/
├── alembic.ini                    ← configuration Alembic
├── alembic/
│   ├── env.py                     ← logique de connexion + config migrations
│   ├── script.py.mako             ← template de génération des fichiers
│   └── versions/
│       ├── 0001_initial.py        ← migration initiale (toutes les tables)
│       └── 0002_machine_notes_example.py  ← exemple de migration future
└── app/
    ├── database.py                ← plus de _add_column_if_missing
    └── models.py                  ← source de vérité du schéma
```
