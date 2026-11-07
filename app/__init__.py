"""ODDO Séquences : mini-app locale d'envoi de séquences email (SMTP/IMAP)."""

APP_NAME = "ODDO Séquences"
VERSION = "2.25.1"
HOST = "127.0.0.1"
PORT = 8765  # V2.6 (bascule) : même adresse que la V1. Les deux ne peuvent donc PAS tourner
#              en même temps : impossible d'envoyer deux fois avec la même boîte mail.
BASE_URL = f"http://{HOST}:{PORT}"
