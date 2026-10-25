# 🎵 Minecraft Sound Studio Pro (ProjectCQD)

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30%2B-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Minecraft Compatibility](https://img.shields.io/badge/Minecraft-1.20--1.21%2B-2A623D?logo=minecraft&logoColor=white)](https://www.minecraft.net/)

**Minecraft Sound Studio Pro (ProjectCQD)** è una Web Application collaborativa sviluppata in Python con **Streamlit** e **PyDub**. Permette a un team di utenti di sostituire in tempo reale oltre 200 suoni di Minecraft e generare automaticamente un **Resource Pack (.zip)** pronto per il gioco.

---

## 🌟 Caratteristiche Principali

- 👥 **Collaborazione in Tempo Reale & Presenza**:
  - Lista degli utenti attualmente online in tempo reale.
  - **Blocco modifiche concorrente**: impedisce a più utenti di modificare contemporaneamente lo stesso suono per evitare sovrascritture accidentali.

- 🎙️ **Registrazione & Caricamento Multi-formato**:
  - Registrazione diretta dal microfono (`st.audio_input`) con cancellazione opzionale del click del mouse.
  - Supporto per una vasta gamma di formati audio: `MP3`, `WAV`, `OGG`, `M4A`, `FLAC`, `AAC`, `OPUS`, `WEBM`, `MP4`, `3GP`, `AMR`, `CAF`.

- ✂️ **Editor Audio Integrato**:
  - Ritaglio di precisione dell'audio tramite slider.
  - Regolazione del guadagno del volume ($\pm 12\text{ dB}$).
  - Conversione automatica in **Mono OGG Vorbis** con bilanciamento del bit-rate per Minecraft.

- 🌐 **Compatibilità Universale (iOS / Safari / Android / PC)**:
  - Conversione automatica al volo delle anteprime in WAV/MP3 per i browser che non supportano i file `.ogg` nativamente (come Safari su iOS).

- ☁️ **Salvataggio Permanente su GitHub (Zero Perdita Dati)**:
  - Risolve il problema del disco temporaneo di Streamlit Community Cloud inviando automaticamente ogni salvataggio/eliminazione su un **branch dati dedicato** (`pack-data`).
  - Sincronizzazione automatica all'avvio dell'app.
  - **Backup notturno automatico** pianificato.

- 🔍 **Filtri Avanzati, Galleria & Ordine Cronologico**:
  - Ricerca rapida per nome o ID Minecraft.
  - Filtri per categoria (Combat, Mob, Blocchi, Ambiente/UI) e stato (*Completati*, *Non completati*, *Controllati*).
  - Ordinamento per data di caricamento (dal più recente al più vecchio).

- 📦 **Esportazione One-Click**:
  - Download diretto del Resource Pack compresso (`ResourcePack_Personalizzata.zip`) contenente `pack.mcmeta`, `sounds.json` e tutte le risorse audio.

---

## 📋 Requisiti di Sistema

1. **Python 3.11** o superiore.
2. **FFmpeg** (necessario per l'elaborazione dei formati audio con PyDub).
   - **Windows** (tramite winget):
     ```cmd
     winget install FFmpeg
     ```
   - **Linux (Ubuntu/Debian)**:
     ```bash
     sudo apt-get update && sudo apt-get install -y ffmpeg
     ```
   - **macOS** (tramite Homebrew):
     ```bash
     brew install ffmpeg
     ```

---

## 🛠️ Installazione Locale

1. **Clona il repository**:
   ```bash
   git clone https://github.com/TUO_UTENTE/projectCQD.git
   cd projectCQD
   ```

2. **Crea un ambiente virtuale e installa le dipendenze**:
   ```bash
   python -m venv venv
   # Su Windows:
   venv\Scripts\activate
   # Su Linux/macOS:
   source venv/bin/activate

   pip install -r requirements.txt
   ```

3. **Avvia l'applicazione**:
   ```bash
   streamlit run projectCQD.py
   ```

---

## ⚙️ Configurazione dei Secrets (per Deploy Cloud)

Per attivare il salvataggio permanente dei dati su **Streamlit Community Cloud**, aggiungi i seguenti parametri nella sezione **Secrets** del tuo progetto (`.streamlit/secrets.toml` locale o dashboard Cloud):

```toml
ACCESS_PASSWORD = "LaTuaPasswordSegreta"
GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
GITHUB_REPO = "tuo-utente/tuo-repo"
GITHUB_DATA_BRANCH = "pack-data"   # Facoltativo (default: pack-data)

# Impostazioni Backup Notturno (Facoltativi)
NIGHTLY_SYNC = "on"
NIGHTLY_SYNC_HOUR = "2"
NIGHTLY_SYNC_TZ = "Europe/Rome"
```

> **Nota sul Token GitHub:** Crea un Personal Access Token (Fine-grained) con i permessi di **Read and Write** sui contenuti del repository (`Contents: Read and Write`).

---

## 📂 Struttura del Progetto

```text
projectCQD/
│
├── projectCQD.py               # Codice sorgente principale dell'applicazione
├── requirements.txt            # Dipendenze Python (streamlit, pydub, requests, ecc.)
├── packages.txt                # Dipendenze di sistema Linux per il Cloud (ffmpeg)
├── original_sounds/            # Cartella contenente i suoni originali di Minecraft
├── ResourcePack_Personalizzata/# Cartella di output del Resource Pack
│   ├── pack.mcmeta
│   ├── checked_sounds.json
│   └── assets/minecraft/
│       ├── sounds.json
│       └── sounds/            # Suoni OGG personalizzati organizzati in sottocartelle
└── README.md
```

---

## 📜 Licenza e Crediti

Progetto realizzato per la community **ProjectCQD**.  
Sviluppato con il contributo di Cai e guidato dall'assistenza AI.