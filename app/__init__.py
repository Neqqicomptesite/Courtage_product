"""Cotalis : prospection et suivi des dossiers pour cabinets de courtage (nom de travail).

Le nom affiché partout vient de APP_NAME ; la variable d'environnement PRODUCT_NAME le remplace
sans toucher au code (renommage du produit, marque blanche).
"""
import os as _os

APP_NAME = _os.environ.get("PRODUCT_NAME", "").strip() or "Cotalis"
VERSION = "3.3.0"
HOST = "127.0.0.1"
PORT = 8765  # V2.6 (bascule) : même adresse que la V1. Les deux ne peuvent donc PAS tourner
#              en même temps : impossible d'envoyer deux fois avec la même boîte mail.
BASE_URL = f"http://{HOST}:{PORT}"
