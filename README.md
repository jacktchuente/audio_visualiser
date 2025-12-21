# Audio Visualisation Web App

Ce projet fournit une application web **self‑hosted** qui permet de téléverser un fichier audio (MP3, WAV, M4A ou OGG) et de générer une vidéo MP4 animée montrant soit l’onde sonore (`showwaves`), soit un spectre (`showspectrum`). La visualisation est réalisée localement via **FFmpeg** et aucune API externe n’est utilisée. L’application est construite avec **FastAPI** côté serveur et du **HTML/JS** minimal côté client.

## Fonctionnalités

* **Upload audio** : un champ fichier accepte les formats audio usuels. La taille maximale par défaut est de 50 Mo (configurable via la variable d’environnement `MAX_UPLOAD_SIZE_MB`). Un fichier image optionnel peut être fourni comme couverture de fond.
* **Paramètres de rendu** : choisissez le style (`wave` ou `spectrum`), la résolution (1280×720 ou 1920×1080), le nombre d’images par seconde (25/30/60), la couleur et le mode de la waveform (`line`, `point`, `p2p`, `cline`), la couleur du fond, le début et la durée à rendre, ainsi qu’une option de normalisation du volume (`loudnorm`). Des presets pratiques sont disponibles : Minimal, Neon et Spectrum.
* **Rendu asynchrone** : chaque upload lance un job identifié par un UUID. L’endpoint `/status/{job_id}` permet de suivre l’état (`queued`, `running`, `done` ou `error`). Une fois le rendu terminé, le MP4 est disponible via `/download/{job_id}`.
* **Nettoyage** : les fichiers uploadés sont supprimés après le rendu et les vidéos finales sont stockées dans `data/outputs/`.
* **Web UI simple** : une page unique (`index.html`) avec un formulaire et une barre de progression effectuant du polling toutes les 2 secondes.

La construction de la waveform utilise le filtre `showwaves` et le spectre utilise `showspectrum`. Le filtre `showwaves` dispose de plusieurs modes (`point`, `line`, `p2p`, `cline`) et accepte un paramètre `colors` qui détermine la couleur du tracé. Les valeurs possibles pour `mode` sont expliquées dans la documentation FFmpeg où il est indiqué que `point`, `line`, `p2p` et `cline` dessinent respectivement des points, des lignes verticales, des segments reliant les points et des lignes centrées【300284597709552†L914-L918】.

## Prérequis

* Python 3.11+
* FFmpeg : doit être installé et accessible via `ffmpeg` et `ffprobe`. Le Dockerfile fournit une image préinstallée.

## Lancer en local (sans Docker)

1. Clonez le dépôt ou copiez les fichiers.
2. Créez un environnement virtuel et installez les dépendances :

   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Assurez‑vous que `ffmpeg` et `ffprobe` sont disponibles :

   ```bash
   ffmpeg -version
   ffprobe -version
   ```

4. Démarrez le serveur :

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

5. Ouvrez votre navigateur à http://localhost:8000 et utilisez l’interface.

## Utilisation via Docker

Le projet inclut un `Dockerfile` et un `docker-compose.yml` pour un déploiement simplifié.

### Construction et exécution manuelle

```bash
docker build -t audio-visualiser .
docker run --rm -p 8000:8000 -v $(pwd)/data:/app/data audio-visualiser
```

### Avec docker‑compose

```bash
docker-compose up --build
```

L’interface sera disponible sur http://localhost:8000. Les fichiers générés sont conservés dans le volume `./data` du répertoire hôte.

## Exemples d’API (cURL)

Uploader un fichier audio et démarrer un job :

```bash
curl -F "audio=@sample.mp3" -F "style=wave" -F "resolution=1280x720" \
     -F "fps=25" -F "color=white" -F "mode=line" \
     http://localhost:8000/upload
```

La réponse contient un `job_id` :

```json
{"job_id": "c4f2a5d1bf95443cb8f7b162e47f1f79", "status": "queued"}
```

Vérifier le statut :

```bash
curl http://localhost:8000/status/c4f2a5d1bf95443cb8f7b162e47f1f79
```

Télécharger la vidéo une fois terminée :

```bash
curl -OJ http://localhost:8000/download/c4f2a5d1bf95443cb8f7b162e47f1f79
```

## Ajouter de nouveaux presets ou filtres

Les presets sont définis côté client dans `app/static/app.js`. Pour en ajouter un nouveau, ajoutez un bouton et implémentez un gestionnaire qui modifie les valeurs du formulaire. Pour créer de nouvelles variations de filtres (par exemple un spectre log‑échelle), modifiez la fonction `build_filter_chain` dans `app/services/ffmpeg.py`.

## Limitations connues

* La gestion des jobs est en mémoire. Un redémarrage du serveur efface les jobs en cours et les vidéos déjà rendues.
* Aucune authentification n’est implémentée ; toute personne ayant accès à l’URL peut lancer des rendus.
* Le nettoyage automatique des fichiers terminés n’est pas encore planifié. Les vidéos terminées restent dans `data/outputs`.
