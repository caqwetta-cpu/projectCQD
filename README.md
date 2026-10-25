\# 🎵 Minecraft Sound Studio - WebApp Python



Una Web Application in Python creata con \*\*Streamlit\*\* e \*\*PyDub\*\* per convertire automaticamente qualsiasi file audio (MP3, WAV, OGG, M4A) in una \*\*Resource Pack (.zip)\*\* perfettamente compatibile con Minecraft (1.20 - 1.21+ / 26.x).



\## 🚀 Caratteristiche

\- \*\*Conversione Automatica Backend\*\*: Converte l'audio da Stereo a \*\*MONO OGG Vorbis (44.1 kHz)\*\* senza dipendere da browser o librerie WebAssembly.

\- \*\*Supporta qualsiasi formato\*\*: Accetta MP3, WAV, M4A, OGG, FLAC.

\- \*\*Nessun Blocco Browser\*\*: Nessun problema di CORS, AdBlock o limite di memoria RAM (`abort()`).

\- \*\*Generazione Struttura Minecraft\*\*: Crea automaticamente `pack.mcmeta` e `assets/minecraft/sounds.json`.



\---



\## 📋 Requisiti di Sistema



1\. \*\*Python 3.8 o superiore\*\*: \[Scarica Python](https://www.python.org/downloads/)

2\. \*\*FFmpeg\*\*: Necessario per la manipolazione di tutti i formati audio.

&#x20;  - \*\*Windows\*\*: Scarica FFmpeg da \[gyan.dev](https://www.gyan.dev/ffmpeg/builds/) e aggiungilo alle variabili d'ambiente (PATH), oppure installalo via Winget:

&#x20;    ```cmd

&#x20;    winget install FFmpeg

&#x20;    ```



\---



\## 🛠️ Installazione ed Esecuzione



1\. \*\*Clona o scarica la cartella del progetto\*\*:

&#x20;  ```bash

&#x20;  cd projectCQD

