# Utilisation d'une image Python légère
FROM python:3.12-slim

# Éviter les fichiers .pyc et activer le logging immédiat
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Répertoire de travail
WORKDIR /app

# Installation des dépendances système nécessaires
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copie des fichiers de dépendances
COPY requirements.txt .

# Installation des bibliothèques Python
RUN pip install --no-cache-dir -r requirements.txt

# Copie du reste du code (en ignorant venv si .dockerignore existe)
COPY . .

# Exposition du port (Hugging Face utilise souvent 7860 par défaut)
EXPOSE 7860

# Commande de démarrage (on utilise le pont main.py)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
