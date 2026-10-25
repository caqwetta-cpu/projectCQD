import hashlib
import hmac
import io
import json
import os
import re
import threading

import streamlit as st
from pydub import AudioSegment
from pydub.utils import which

# ---------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------
st.set_page_config(page_title="Minecraft Sound Studio Pro", page_icon="🎵", layout="wide")

ORIGINAL_SOUNDS_DIR = "original_sounds"
OUTPUT_PACK_DIR = "ResourcePack_Personalizzata"
SOUNDS_DIR = os.path.join(OUTPUT_PACK_DIR, "assets", "minecraft", "sounds")
SOUNDS_JSON_PATH = os.path.join(OUTPUT_PACK_DIR, "assets", "minecraft", "sounds.json")
MCMETA_PATH = os.path.join(OUTPUT_PACK_DIR, "pack.mcmeta")
CHECKED_JSON_PATH = os.path.join(OUTPUT_PACK_DIR, "checked_sounds.json")


def _load_password():
    """Password da variabile d'ambiente CQD_PASSWORD o da .streamlit/secrets.toml (chiave ACCESS_PASSWORD)."""
    env_pw = os.environ.get("CQD_PASSWORD")
    if env_pw:
        return env_pw
    try:
        return st.secrets["ACCESS_PASSWORD"]
    except Exception:
        return "Caccadura24"


ACCESS_PASSWORD = _load_password()

# pydub ha bisogno di ffmpeg
if not which("ffmpeg"):
    st.error(
        "❌ **ffmpeg non trovato.** pydub ne ha bisogno per leggere/convertire l'audio "
        "(mp3, m4a, registrazioni del microfono, export OGG). Installalo e aggiungilo al PATH "
        "(Windows: `winget install ffmpeg`), poi riavvia l'app."
    )
    st.stop()

# ---------------------------------------------------------
# CSS (layout registratore pulito)
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    div[data-testid="stAudioInput"] {
        padding: 10px 15px !important;
        background-color: #1a1d24 !important;
        border: 2px solid #ff3b30 !important;
        border-radius: 12px !important;
        margin-top: 8px !important;
        margin-bottom: 12px !important;
        box-shadow: 0 4px 12px rgba(255, 59, 48, 0.25) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# HELPER AUDIO & CHECKED
# ---------------------------------------------------------
@st.cache_resource
def get_write_lock():
    """Lock condiviso tra tutte le sessioni."""
    return threading.Lock()


@st.cache_data(show_spinner=False, max_entries=64)
def playable_audio(path, mtime, compat):
    """Restituisce (bytes, mime) pronti per st.audio."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 200 or (path.lower().endswith(".ogg") and not data.startswith(b"OggS")):
        raise ValueError(f"file vuoto o non valido ({len(data)} byte): rifallo/ricopialo")
    if not compat:
        return data, "audio/ogg"
    try:
        seg = AudioSegment.from_file(io.BytesIO(data))
        buf = io.BytesIO()
        try:
            seg.export(buf, format="mp3", bitrate="256k")
            return buf.getvalue(), "audio/mpeg"
        except Exception:
            buf = io.BytesIO()
            seg.export(buf, format="wav")
            return buf.getvalue(), "audio/wav"
    except Exception:
        return data, "audio/ogg"


def show_player(path):
    """Mostra un player per un file su disco."""
    if not path or not os.path.exists(path):
        st.error("⚠️ File audio non trovato.")
        return
    try:
        data, mime = playable_audio(path, os.path.getmtime(path), st.session_state.get("compat_audio", False))
        st.audio(data, format=mime)
    except Exception as e:
        st.error(f"⚠️ Impossibile leggere il file: {e}")


@st.cache_data(show_spinner=False, max_entries=8)
def decode_audio(data: bytes) -> AudioSegment:
    """Decodifica una sola volta."""
    return AudioSegment.from_file(io.BytesIO(data))


def get_checked_sounds():
    """Legge la mappa dei suoni contrassegnati come Controllato."""
    if os.path.exists(CHECKED_JSON_PATH):
        try:
            with open(CHECKED_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def set_sound_checked(sound_id, is_checked):
    """Salva la spunta Controllato su file JSON."""
    with get_write_lock():
        data = get_checked_sounds()
        data[sound_id] = is_checked
        _atomic_write_json(CHECKED_JSON_PATH, data)


def delete_sound_realtime(sound_id, sound_file_path):
    """Rimuove l'audio dal disco e aggiorna sounds.json."""
    file_key = sound_file_path.replace(".ogg", "")
    target_ogg_path = os.path.join(SOUNDS_DIR, f"{file_key}.ogg")

    with get_write_lock():
        if os.path.exists(target_ogg_path):
            try:
                os.remove(target_ogg_path)
            except OSError:
                pass
        sounds_data = get_saved_sounds_manifest()
        if sound_id in sounds_data:
            del sounds_data[sound_id]
            _atomic_write_json(SOUNDS_JSON_PATH, sounds_data)


# ---------------------------------------------------------
# 1. AUTENTICAZIONE E SESSIONE ISOLATA
# ---------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "user_name" not in st.session_state:
    st.session_state["user_name"] = ""

if not st.session_state["authenticated"]:
    st.title("🔒 Accesso Riservato - Minecraft Sound Studio Pro")
    st.write("Inserisci il tuo Nickname e la Password per accedere al progetto.")

    with st.form("login_form"):
        input_name = st.text_input("👤 Il tuo Nome / Nickname:")
        input_pass = st.text_input("🔑 Password di Accesso:", type="password")
        submit_btn = st.form_submit_button("🚀 Accedi allo Studio", type="primary")

        if submit_btn:
            if not hmac.compare_digest(input_pass.encode("utf-8"), ACCESS_PASSWORD.encode("utf-8")):
                st.error("❌ Password errata! Riprova.")
            elif not input_name.strip():
                st.warning("⚠️ Inserisci un nome utente valido.")
            else:
                st.session_state["authenticated"] = True
                st.session_state["user_name"] = input_name.strip()[:40]
                st.rerun()
    st.stop()

# ---------------------------------------------------------
# 2. CERCA FILE ORIGINALI
# ---------------------------------------------------------
def find_original_sound_file(base_dir, relative_path):
    exact_path = os.path.join(base_dir, relative_path)
    if os.path.exists(exact_path):
        return exact_path

    dir_name, file_name = os.path.split(relative_path)
    stem, ext = os.path.splitext(file_name)
    base_stem = stem.rstrip("0123456789")

    search_dir = os.path.join(base_dir, dir_name)
    if os.path.isdir(search_dir):
        pattern = re.compile(rf"^{re.escape(base_stem)}[_\-]?\d*{re.escape(ext)}$", re.IGNORECASE)
        for f in sorted(os.listdir(search_dir)):
            if pattern.match(f):
                return os.path.join(search_dir, f)
    return None

# ---------------------------------------------------------
# 3. LISTA COMPLETA 200 SUONI MINECRAFT
# ---------------------------------------------------------
VANILLA_SOUNDS_MAP = [
    # --- ⚔️ COMBAT, DANNI & STRUMENTI (50) ---
    {"id": "entity.player.hurt", "file": "damage/hit1.ogg", "label": "Giocatore - Danno Subito", "cat": "⚔️ Combat & Danni"},
    {"id": "entity.player.big_fall", "file": "damage/fallbig.ogg", "label": "Giocatore - Caduta Grande", "cat": "⚔️ Combat & Danni"},
    {"id": "entity.player.small_fall", "file": "damage/fallsmall.ogg", "label": "Giocatore - Caduta Piccola", "cat": "⚔️ Combat & Danni"},
    {"id": "entity.player.attack.crit", "file": "entity/player/attack/crit1.ogg", "label": "Attacco - Critico", "cat": "⚔️ Combat & Danni"},
    {"id": "entity.player.attack.knockback", "file": "entity/player/attack/knockback1.ogg", "label": "Attacco - Contraccolpo", "cat": "⚔️ Combat & Danni"},
    {"id": "entity.player.attack.strong", "file": "entity/player/attack/strong1.ogg", "label": "Attacco - Forte", "cat": "⚔️ Combat & Danni"},
    {"id": "entity.player.attack.sweep", "file": "entity/player/attack/sweep1.ogg", "label": "Attacco - Fendente", "cat": "⚔️ Combat & Danni"},
    {"id": "entity.player.attack.weak", "file": "entity/player/attack/weak1.ogg", "label": "Attacco - Debole", "cat": "⚔️ Combat & Danni"},
    {"id": "item.shield.block", "file": "item/shield/block1.ogg", "label": "Scudo - Parata", "cat": "⚔️ Combat & Danni"},
    {"id": "item.bow.shoot", "file": "random/bow.ogg", "label": "Arco - Tiro", "cat": "⚔️ Combat & Danni"},
    {"id": "entity.arrow.hit", "file": "random/bowhit1.ogg", "label": "Freccia - Impatto", "cat": "⚔️ Combat & Danni"},
    {"id": "item.crossbow.shoot", "file": "item/crossbow/shoot1.ogg", "label": "Balestra - Sparo", "cat": "⚔️ Combat & Danni"},
    {"id": "item.crossbow.loading_end", "file": "item/crossbow/loading_end.ogg", "label": "Balestra - Caricamento Completato", "cat": "⚔️ Combat & Danni"},
    {"id": "item.trident.throw", "file": "item/trident/throw1.ogg", "label": "Tridente - Lancio", "cat": "⚔️ Combat & Danni"},
    {"id": "item.trident.thunder", "file": "item/trident/thunder1.ogg", "label": "Tridente - Fulmine", "cat": "⚔️ Combat & Danni"},
    {"id": "item.trident.return", "file": "item/trident/return1.ogg", "label": "Tridente - Ritorno", "cat": "⚔️ Combat & Danni"},
    {"id": "item.mace.smash_ground", "file": "item/mace/smash_ground1.ogg", "label": "Mazza - Impatto Pesante", "cat": "⚔️ Combat & Danni"},
    {"id": "item.mace.smash_air", "file": "item/mace/smash_air1.ogg", "label": "Mazza - Colpo in Aria", "cat": "⚔️ Combat & Danni"},
    {"id": "item.totem.use", "file": "item/totem/use_totem.ogg", "label": "Totem dell'Immortalità", "cat": "⚔️ Combat & Danni"},
    {"id": "item.armor.equip_diamond", "file": "item/armor/equip_diamond1.ogg", "label": "Armatura - Diamante", "cat": "⚔️ Combat & Danni"},
    {"id": "item.armor.equip_netherite", "file": "item/armor/equip_netherite1.ogg", "label": "Armatura - Netherite", "cat": "⚔️ Combat & Danni"},
    {"id": "item.armor.equip_iron", "file": "item/armor/equip_iron1.ogg", "label": "Armatura - Ferro", "cat": "⚔️ Combat & Danni"},
    {"id": "item.armor.equip_gold", "file": "item/armor/equip_gold1.ogg", "label": "Armatura - Oro", "cat": "⚔️ Combat & Danni"},
    {"id": "item.armor.equip_chain", "file": "item/armor/equip_chain1.ogg", "label": "Armatura - Maglia di Ferro", "cat": "⚔️ Combat & Danni"},
    {"id": "item.armor.equip_leather", "file": "item/armor/equip_leather1.ogg", "label": "Armatura - Cuoio", "cat": "⚔️ Combat & Danni"},
    {"id": "item.armor.equip_generic", "file": "item/armor/equip_generic1.ogg", "label": "Armatura - Generica", "cat": "⚔️ Combat & Danni"},
    {"id": "item.axe.strip", "file": "item/axe/strip1.ogg", "label": "Ascia - Scortecciare", "cat": "⚔️ Combat & Danni"},
    {"id": "item.axe.scrape", "file": "item/axe/scrape1.ogg", "label": "Ascia - Raschiare Rame", "cat": "⚔️ Combat & Danni"},
    {"id": "item.axe.wax_off", "file": "item/axe/wax_off1.ogg", "label": "Ascia - Rimuovere Cera", "cat": "⚔️ Combat & Danni"},
    {"id": "item.hoe.till", "file": "item/hoe/till1.ogg", "label": "Zappa - Zappare Terra", "cat": "⚔️ Combat & Danni"},
    {"id": "item.shovel.flatten", "file": "item/shovel/flatten1.ogg", "label": "Pala - Creare Sentiero", "cat": "⚔️ Combat & Danni"},
    {"id": "item.honeycomb.wax_on", "file": "item/honeycomb/wax_on1.ogg", "label": "Favo - Applicare Cera", "cat": "⚔️ Combat & Danni"},
    {"id": "item.flintandsteel.use", "file": "fire/ignite.ogg", "label": "Acciarino - Accendere Fuoco", "cat": "⚔️ Combat & Danni"},
    {"id": "item.bottle.empty", "file": "item/bottle/empty1.ogg", "label": "Ampolla - Svuotare", "cat": "⚔️ Combat & Danni"},
    {"id": "item.bottle.fill", "file": "item/bottle/fill1.ogg", "label": "Ampolla - Riempire", "cat": "⚔️ Combat & Danni"},
    {"id": "item.bucket.empty", "file": "item/bucket/empty1.ogg", "label": "Secchio - Svuotare Acqua", "cat": "⚔️ Combat & Danni"},
    {"id": "item.bucket.fill", "file": "item/bucket/fill1.ogg", "label": "Secchio - Riempire Acqua", "cat": "⚔️ Combat & Danni"},
    {"id": "item.bucket.empty_lava", "file": "item/bucket/empty_lava1.ogg", "label": "Secchio - Svuotare Lava", "cat": "⚔️ Combat & Danni"},
    {"id": "item.bucket.fill_lava", "file": "item/bucket/fill_lava1.ogg", "label": "Secchio - Riempire Lava", "cat": "⚔️ Combat & Danni"},
    {"id": "item.spyglass.use", "file": "item/spyglass/use.ogg", "label": "Cannocchiale - Usa", "cat": "⚔️ Combat & Danni"},
    {"id": "item.spyglass.stop_using", "file": "item/spyglass/stop.ogg", "label": "Cannocchiale - Chiudi", "cat": "⚔️ Combat & Danni"},
    {"id": "item.brush.brushing.generic", "file": "item/brush/brushing_generic1.ogg", "label": "Spazzola - Spazzolare", "cat": "⚔️ Combat & Danni"},
    {"id": "item.bundle.insert", "file": "item/bundle/insert1.ogg", "label": "Sacca - Inserire Oggetto", "cat": "⚔️ Combat & Danni"},
    {"id": "item.bundle.remove_one", "file": "item/bundle/remove_one1.ogg", "label": "Sacca - Estrarre Oggetto", "cat": "⚔️ Combat & Danni"},
    {"id": "item.elytra.flying", "file": "item/elytra/elytra_loop.ogg", "label": "Elitre - Volo", "cat": "⚔️ Combat & Danni"},
    {"id": "item.goat_horn.sound.0", "file": "item/goat_horn/call0.ogg", "label": "Corno di Capra - Suono", "cat": "⚔️ Combat & Danni"},
    {"id": "enchant.thorns.hit", "file": "enchant/thorns/hit1.ogg", "label": "Spine - Danno Inflitto", "cat": "⚔️ Combat & Danni"},
    {"id": "enchant.soulspeed.step", "file": "enchant/soulspeed/soulspeed1.ogg", "label": "Velocità dell'Anima - Passo", "cat": "⚔️ Combat & Danni"},
    {"id": "entity.player.burp", "file": "random/burp.ogg", "label": "Giocatore - Rutto", "cat": "⚔️ Combat & Danni"},
    {"id": "entity.item.pickup", "file": "random/pop.ogg", "label": "Oggetto - Raccogliere", "cat": "⚔️ Combat & Danni"},

    # --- 👾 MOB & CREATURE (60) ---
    {"id": "entity.creeper.primed", "file": "random/fuse.ogg", "label": "Creeper - Innesco (Sssss)", "cat": "👾 Mob & Creature"},
    {"id": "entity.creeper.death", "file": "mob/creeper/death.ogg", "label": "Creeper - Morte", "cat": "👾 Mob & Creature"},
    {"id": "entity.zombie.ambient", "file": "mob/zombie/say1.ogg", "label": "Zombie - Verso", "cat": "👾 Mob & Creature"},
    {"id": "entity.zombie.hurt", "file": "mob/zombie/hurt1.ogg", "label": "Zombie - Danno Subito", "cat": "👾 Mob & Creature"},
    {"id": "entity.zombie.death", "file": "mob/zombie/death.ogg", "label": "Zombie - Morte", "cat": "👾 Mob & Creature"},
    {"id": "entity.skeleton.ambient", "file": "mob/skeleton/say1.ogg", "label": "Scheletro - Verso", "cat": "👾 Mob & Creature"},
    {"id": "entity.skeleton.hurt", "file": "mob/skeleton/hurt1.ogg", "label": "Scheletro - Danno Subito", "cat": "👾 Mob & Creature"},
    {"id": "entity.skeleton.death", "file": "mob/skeleton/death.ogg", "label": "Scheletro - Morte", "cat": "👾 Mob & Creature"},
    {"id": "entity.spider.ambient", "file": "mob/spider/say1.ogg", "label": "Ragno - Verso", "cat": "👾 Mob & Creature"},
    {"id": "entity.spider.death", "file": "mob/spider/death.ogg", "label": "Ragno - Morte", "cat": "👾 Mob & Creature"},
    {"id": "entity.enderman.stare", "file": "mob/endermen/stare.ogg", "label": "Enderman - Sguardo Fisso", "cat": "👾 Mob & Creature"},
    {"id": "entity.enderman.scream", "file": "mob/endermen/scream1.ogg", "label": "Enderman - Urlo", "cat": "👾 Mob & Creature"},
    {"id": "entity.enderman.teleport", "file": "mob/endermen/portal.ogg", "label": "Enderman - Teletrasporto", "cat": "👾 Mob & Creature"},
    {"id": "entity.ghast.scream", "file": "mob/ghast/scream1.ogg", "label": "Ghast - Urlo", "cat": "👾 Mob & Creature"},
    {"id": "entity.ghast.warn", "file": "mob/ghast/moan1.ogg", "label": "Ghast - Lamento", "cat": "👾 Mob & Creature"},
    {"id": "entity.ghast.shoot", "file": "mob/ghast/fireball4.ogg", "label": "Ghast - Palla di Fuoco", "cat": "👾 Mob & Creature"},
    {"id": "entity.warden.heartbeat", "file": "mob/warden/heartbeat_1.ogg", "label": "Warden - Battito Cardiaco", "cat": "👾 Mob & Creature"},
    {"id": "entity.warden.sonic_boom", "file": "mob/warden/sonic_boom1.ogg", "label": "Warden - Raggio Sonico", "cat": "👾 Mob & Creature"},
    {"id": "entity.warden.roar", "file": "mob/warden/roar_1.ogg", "label": "Warden - Ruggito", "cat": "👾 Mob & Creature"},
    {"id": "entity.ender_dragon.growl", "file": "mob/enderdragon/growl1.ogg", "label": "Drago dell'End - Ruggito", "cat": "👾 Mob & Creature"},
    {"id": "entity.ender_dragon.flap", "file": "mob/enderdragon/wings1.ogg", "label": "Drago dell'End - Battito d'Ali", "cat": "👾 Mob & Creature"},
    {"id": "entity.wither.spawn", "file": "mob/wither/spawn.ogg", "label": "Wither - Evocazione", "cat": "👾 Mob & Creature"},
    {"id": "entity.wither.shoot", "file": "mob/wither/shoot.ogg", "label": "Wither - Sparo Teschio", "cat": "👾 Mob & Creature"},
    {"id": "entity.blaze.breathe", "file": "mob/blaze/breathe1.ogg", "label": "Blaze - Respiro", "cat": "👾 Mob & Creature"},
    {"id": "entity.blaze.death", "file": "mob/blaze/death.ogg", "label": "Blaze - Morte", "cat": "👾 Mob & Creature"},
    {"id": "entity.slime.squish", "file": "mob/slime/big1.ogg", "label": "Slime - Salto Grande", "cat": "👾 Mob & Creature"},
    {"id": "entity.phantom.swoop", "file": "mob/phantom/swoop1.ogg", "label": "Phantom - Attacco in Picchiata", "cat": "👾 Mob & Creature"},
    {"id": "entity.breeze.wind_burst", "file": "mob/breeze/wind_burst1.ogg", "label": "Breeze - Raffica di Vento", "cat": "👾 Mob & Creature"},
    {"id": "entity.cow.ambient", "file": "mob/cow/say1.ogg", "label": "Mucca - Verso", "cat": "👾 Mob & Creature"},
    {"id": "entity.pig.ambient", "file": "mob/pig/say1.ogg", "label": "Maiale - Verso", "cat": "👾 Mob & Creature"},
    {"id": "entity.sheep.ambient", "file": "mob/sheep/say1.ogg", "label": "Pecora - Verso", "cat": "👾 Mob & Creature"},
    {"id": "entity.chicken.ambient", "file": "mob/chicken/say1.ogg", "label": "Gallina - Verso", "cat": "👾 Mob & Creature"},
    {"id": "entity.wolf.ambient", "file": "mob/wolf/classic/bark1.ogg", "label": "Lupo - Abbaio", "cat": "👾 Mob & Creature"},
    {"id": "entity.wolf.growl", "file": "mob/wolf/classic/growl1.ogg", "label": "Lupo - Ringhio", "cat": "👾 Mob & Creature"},
    {"id": "entity.cat.ambient", "file": "mob/cat/meow1.ogg", "label": "Gatto - Miagolio", "cat": "👾 Mob & Creature"},
    {"id": "entity.cat.purr", "file": "mob/cat/purr1.ogg", "label": "Gatto - Fusa", "cat": "👾 Mob & Creature"},
    {"id": "entity.villager.yes", "file": "mob/villager/yes1.ogg", "label": "Villico - Si (Scambio)", "cat": "👾 Mob & Creature"},
    {"id": "entity.villager.no", "file": "mob/villager/no1.ogg", "label": "Villico - No", "cat": "👾 Mob & Creature"},
    {"id": "entity.villager.trade", "file": "mob/villager/haggle1.ogg", "label": "Villico - Trattativa", "cat": "👾 Mob & Creature"},
    {"id": "entity.pillager.celebrate", "file": "mob/pillager/celebrate1.ogg", "label": "Saccheggiatore - Esultanza", "cat": "👾 Mob & Creature"},
    {"id": "entity.ravager.roar", "file": "mob/ravager/roar1.ogg", "label": "Devastatore - Ruggito", "cat": "👾 Mob & Creature"},
    {"id": "entity.witch.drink", "file": "entity/witch/drink1.ogg", "label": "Strega - Bere Pozione", "cat": "👾 Mob & Creature"},
    {"id": "entity.vex.charge", "file": "mob/vex/charge1.ogg", "label": "Vex - Carica", "cat": "👾 Mob & Creature"},
    {"id": "entity.allay.ambient_with_item", "file": "mob/allay/idle_with_item1.ogg", "label": "Allay - Verso con Oggetto", "cat": "👾 Mob & Creature"},
    {"id": "entity.axolotl.idle_water", "file": "mob/axolotl/idle1.ogg", "label": "Axolotl - Verso", "cat": "👾 Mob & Creature"},
    {"id": "entity.bee.loop", "file": "mob/bee/loop1.ogg", "label": "Ape - Ronzio", "cat": "👾 Mob & Creature"},
    {"id": "entity.bee.sting", "file": "mob/bee/sting.ogg", "label": "Ape - Pungiglione", "cat": "👾 Mob & Creature"},
    {"id": "entity.frog.ambient", "file": "mob/frog/idle1.ogg", "label": "Rana - Gracidio", "cat": "👾 Mob & Creature"},
    {"id": "entity.goat.screaming.ambient", "file": "mob/goat/scream1.ogg", "label": "Capra - Urlo", "cat": "👾 Mob & Creature"},
    {"id": "entity.camel.dash", "file": "mob/camel/dash1.ogg", "label": "Cammello - Scatto", "cat": "👾 Mob & Creature"},
    {"id": "entity.panda.sneeze", "file": "mob/panda/sneeze1.ogg", "label": "Panda - Starnuto", "cat": "👾 Mob & Creature"},
    {"id": "entity.parrot.ambient", "file": "mob/parrot/idle1.ogg", "label": "Pappagallo - Verso", "cat": "👾 Mob & Creature"},
    {"id": "entity.dolphin.play", "file": "mob/dolphin/play1.ogg", "label": "Delfino - Gioco", "cat": "👾 Mob & Creature"},
    {"id": "entity.fox.screech", "file": "mob/fox/screech1.ogg", "label": "Volpe - Urlo Notturno", "cat": "👾 Mob & Creature"},
    {"id": "entity.sniffer.sniffing", "file": "mob/sniffer/sniffing1.ogg", "label": "Sniffer - Annusare", "cat": "👾 Mob & Creature"},
    {"id": "entity.strider.ambient", "file": "mob/strider/idle1.ogg", "label": "Magmatico - Verso", "cat": "👾 Mob & Creature"},
    {"id": "entity.hoglin.angry", "file": "mob/hoglin/angry1.ogg", "label": "Hoglin - Rabbia", "cat": "👾 Mob & Creature"},
    {"id": "entity.piglin.admiring_item", "file": "mob/piglin/admire1.ogg", "label": "Piglin - Ammirare Oro", "cat": "👾 Mob & Creature"},
    {"id": "entity.zombified_piglin.angry", "file": "mob/zombified_piglin/zpigangry1.ogg", "label": "Piglin Zombie - Rabbia", "cat": "👾 Mob & Creature"},
    {"id": "entity.iron_golem.attack", "file": "mob/irongolem/throw.ogg", "label": "Golem di Ferro - Attacco", "cat": "👾 Mob & Creature"},

    # --- 🧱 BLOCCHI & INTERAZIONI (50) ---
    {"id": "block.stone.break", "file": "dig/stone1.ogg", "label": "Pietra - Rompere", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.stone.step", "file": "step/stone1.ogg", "label": "Pietra - Passo", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.grass.break", "file": "dig/grass1.ogg", "label": "Erba - Rompere", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.grass.step", "file": "step/grass1.ogg", "label": "Erba - Passo", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.wood.break", "file": "dig/wood1.ogg", "label": "Legno - Rompere", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.wood.step", "file": "step/wood1.ogg", "label": "Legno - Passo", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.sand.break", "file": "dig/sand1.ogg", "label": "Sabbia - Rompere", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.gravel.break", "file": "dig/gravel1.ogg", "label": "Ghiaia - Rompere", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.glass.break", "file": "random/glass1.ogg", "label": "Vetro - Rompere", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.amethyst_block.break", "file": "block/amethyst/break1.ogg", "label": "Ametista - Rompere", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.amethyst_block.resonate", "file": "block/amethyst/resonate1.ogg", "label": "Ametista - Risonanza", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.ancient_debris.break", "file": "block/ancient_debris/break1.ogg", "label": "Detriti Antichi - Rompere", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.anvil.use", "file": "random/anvil_use.ogg", "label": "Incudine - Uso", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.anvil.land", "file": "random/anvil_land.ogg", "label": "Incudine - Caduta", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.chest.open", "file": "random/chestopen.ogg", "label": "Cassa - Apertura", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.chest.close", "file": "random/chestclosed.ogg", "label": "Cassa - Chiusura", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.wooden_door.open", "file": "random/door_open.ogg", "label": "Porta in Legno - Apri", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.wooden_door.close", "file": "random/door_close.ogg", "label": "Porta in Legno - Chiudi", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.iron_door.open", "file": "block/iron_door/open1.ogg", "label": "Porta in Ferro - Apri", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.fence_gate.open", "file": "block/fence_gate/open1.ogg", "label": "Cancelletto - Apri", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.shulker_box.open", "file": "block/shulker_box/open.ogg", "label": "Cassa di Shulker - Apri", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.barrel.open", "file": "block/barrel/open1.ogg", "label": "Barile - Apri", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.beacon.activate", "file": "block/beacon/activate.ogg", "label": "Beacon - Attivazione", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.beacon.deactivate", "file": "block/beacon/deactivate.ogg", "label": "Beacon - Disattivazione", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.bell.use", "file": "block/bell/bell_use01.ogg", "label": "Campana - Rintocco", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.respawn_anchor.charge", "file": "block/respawn_anchor/charge1.ogg", "label": "Ancora di Rinascita - Carica", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.conduit.activate", "file": "block/conduit/activate.ogg", "label": "Condotto - Attivazione", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.sculk_shrieker.shriek", "file": "block/sculk_shrieker/shriek1.ogg", "label": "Sculk Shrieker - Urlo", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.sculk_sensor.clicking", "file": "block/sculk_sensor/sculk_clicking1.ogg", "label": "Sensore Sculk - Attivazione", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.campfire.crackle", "file": "block/campfire/crackle1.ogg", "label": "Fuoco da Campo - Crepitio", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.candle.extinguish", "file": "block/candle/extinguish1.ogg", "label": "Candela - Spegnere", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.decorated_pot.shatter", "file": "block/decorated_pot/shatter1.ogg", "label": "Vaso Decorato - Frantumazione", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.copper_bulb.toggle", "file": "block/copper_bulb/toggle.ogg", "label": "Bulbo di Rame - Interruttore", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.piston.extend", "file": "tile/piston/out.ogg", "label": "Pistone - Estensione", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.piston.contract", "file": "tile/piston/in.ogg", "label": "Pistone - Contrazione", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.furnace.fire_crackle", "file": "block/furnace/fire_crackle1.ogg", "label": "Fornace - Fuoco", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.grindstone.use", "file": "block/grindstone/grindstone1.ogg", "label": "Mola - Uso", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.lantern.place", "file": "block/lantern/place1.ogg", "label": "Lanterna - Posizionare", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.sponge.absorb", "file": "block/sponge/absorb1.ogg", "label": "Spugna - Assorbimento Acqua", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.honeyblock.slide", "file": "block/honeyblock/slide1.ogg", "label": "Blocco di Miele - Scivolata", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.composter.ready", "file": "block/composter/ready1.ogg", "label": "Compostiera - Pronta", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.end_portal_frame.fill", "file": "block/end_portal/eyeplace1.ogg", "label": "Portale End - Occhio Posizionato", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.ender_chest.open", "file": "block/enderchest/open.ogg", "label": "Cassa Ender - Apri", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "entity.generic.explode", "file": "random/explode1.ogg", "label": "Esplosione - Generica", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "entity.generic.splash", "file": "liquid/splash.ogg", "label": "Acqua - Tuffo", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "entity.generic.burn", "file": "liquid/lava.ogg", "label": "Lava - Bruciare", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.lava.pop", "file": "liquid/lavapop.ogg", "label": "Lava - Schizzo/Bolla", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "entity.minecart.riding", "file": "minecart/inside.ogg", "label": "Carrello - Corsa sui Binari", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.pointed_dripstone.drip_lava", "file": "block/pointed_dripstone/drip_lava1.ogg", "label": "Gocciolatoio - Goccia Lava", "cat": "🧱 Blocchi & Interazioni"},
    {"id": "block.chiseled_bookshelf.insert", "file": "block/chiseled_bookshelf/insert1.ogg", "label": "Libreria Incisoria - Inserisci Libro", "cat": "🧱 Blocchi & Interazioni"},

    # --- 🎵 AMBIENTE, UI & DISCHI (40) ---
    {"id": "ambient.cave", "file": "ambient/cave/cave1.ogg", "label": "Caverna - Suono Misterioso", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "entity.lightning_bolt.thunder", "file": "ambient/weather/thunder1.ogg", "label": "Meteo - Tuono", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "weather.rain", "file": "ambient/weather/rain1.ogg", "label": "Meteo - Pioggia", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "block.portal.ambient", "file": "portal/portal.ogg", "label": "Portale Nether - Ambiente", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "block.portal.travel", "file": "portal/travel.ogg", "label": "Portale Nether - Teletrasporto", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "block.portal.trigger", "file": "portal/trigger.ogg", "label": "Portale Nether - Innesco", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "entity.player.levelup", "file": "random/levelup.ogg", "label": "Giocatore - Avanzamento Livello XP", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "entity.experience_orb.pickup", "file": "random/orb.ogg", "label": "Sfera XP - Riconoscimento", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "ui.button.click", "file": "random/click.ogg", "label": "Interfaccia - Click Pulsante", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "ui.toast.challenge_complete", "file": "ui/toast/challenge_complete.ogg", "label": "Interfaccia - Sfida Completata", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "ui.stonecutter.take_result", "file": "ui/stonecutter/cut1.ogg", "label": "Tagliapietre - Taglio", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "ui.cartography_table.take_result", "file": "ui/cartography_table/drawmap1.ogg", "label": "Tavolo Cartografico - Mappa", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "event.raid.horn", "file": "event/raid/raidhorn_01.ogg", "label": "Incursione - Corno di Guerra", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "block.note_block.harp", "file": "note/harp.ogg", "label": "Blocco Nota - Arpa", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "block.note_block.pling", "file": "note/pling.ogg", "label": "Blocco Nota - Pling", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "block.note_block.bass", "file": "note/bass.ogg", "label": "Blocco Nota - Basso", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "block.note_block.bell", "file": "note/bell.ogg", "label": "Blocco Nota - Campana", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "block.note_block.flute", "file": "note/flute.ogg", "label": "Blocco Nota - Flauto", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "block.note_block.guitar", "file": "note/guitar.ogg", "label": "Blocco Nota - Chitarra", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.pigstep", "file": "records/pigstep.ogg", "label": "Disco Musicale - Pigstep", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.cat", "file": "records/cat.ogg", "label": "Disco Musicale - Cat", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.otherside", "file": "records/otherside.ogg", "label": "Disco Musicale - Otherside", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.5", "file": "records/5.ogg", "label": "Disco Musicale - 5", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.relic", "file": "records/relic.ogg", "label": "Disco Musicale - Relic", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.13", "file": "records/13.ogg", "label": "Disco Musicale - 13", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.blocks", "file": "records/blocks.ogg", "label": "Disco Musicale - Blocks", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.chirp", "file": "records/chirp.ogg", "label": "Disco Musicale - Chirp", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.far", "file": "records/far.ogg", "label": "Disco Musicale - Far", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.mall", "file": "records/mall.ogg", "label": "Disco Musicale - Mall", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.mellohi", "file": "records/mellohi.ogg", "label": "Disco Musicale - Mellohi", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.stal", "file": "records/stal.ogg", "label": "Disco Musicale - Stal", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.strad", "file": "records/strad.ogg", "label": "Disco Musicale - Strad", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.ward", "file": "records/ward.ogg", "label": "Disco Musicale - Ward", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.11", "file": "records/11.ogg", "label": "Disco Musicale - 11", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music_disc.wait", "file": "records/wait.ogg", "label": "Disco Musicale - Wait", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "entity.generic.drink", "file": "random/drink.ogg", "label": "Giocatore - Bere", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "entity.generic.eat", "file": "random/eat1.ogg", "label": "Giocatore - Mangiare", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music.creative", "file": "music/game/creative/aria_math.ogg", "label": "Musica - Modalità Creativa", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music.menu", "file": "music/menu/beginning_2.ogg", "label": "Musica - Menu Principale", "cat": "🎵 Ambiente, UI & Dischi"},
    {"id": "music.dragon", "file": "music/game/end/boss.ogg", "label": "Musica - Boss Drago dell'End", "cat": "🎵 Ambiente, UI & Dischi"}
]

LEGACY_ENTRIES = [
    ('entity.player.hurt', 'entity/player/hurt1.ogg', 'entity.player.hurt', 'damage/hit1.ogg'),
    ('entity.player.big_fall', 'entity/player/big_fall.ogg', 'entity.player.big_fall', 'damage/fallbig.ogg'),
    ('entity.player.small_fall', 'entity/player/small_fall.ogg', 'entity.player.small_fall', 'damage/fallsmall.ogg'),
    ('item.bow.shoot', 'item/bow/shoot.ogg', 'item.bow.shoot', 'random/bow.ogg'),
    ('entity.arrow.hit', 'entity/arrow/hit1.ogg', 'entity.arrow.hit', 'random/bowhit1.ogg'),
    ('entity.ghast.shoot', 'mob/ghast/fireball.ogg', 'entity.ghast.shoot', 'mob/ghast/fireball4.ogg'),
    ('entity.warden.sonic_boom', 'mob/warden/sonic_boom.ogg', 'entity.warden.sonic_boom', 'mob/warden/sonic_boom1.ogg'),
    ('entity.witch.drink', 'mob/witch/drink1.ogg', 'entity.witch.drink', 'entity/witch/drink1.ogg'),
    ('block.bell.use', 'block/bell/bell_use.ogg', 'block.bell.use', 'block/bell/bell_use01.ogg'),
    ('event.raid.horn', 'event/raid/raidhorn_.ogg', 'event.raid.horn', 'event/raid/raidhorn_01.ogg'),
    ('music.menu', 'music/menu/menu1.ogg', 'music.menu', 'music/menu/beginning_2.ogg'),
    ('music.credits', 'music/credits.ogg', 'music.dragon', 'music/game/end/boss.ogg'),
    ('item.flintandsteel.ignite', 'fire/ignite.ogg', 'item.flintandsteel.use', 'fire/ignite.ogg'),
    ('entity.wolf.bark', 'mob/wolf/classic/bark1.ogg', 'entity.wolf.ambient', 'mob/wolf/classic/bark1.ogg'),
    ('ambient.weather.thunder', 'ambient/weather/thunder1.ogg', 'entity.lightning_bolt.thunder', 'ambient/weather/thunder1.ogg'),
    ('ambient.weather.rain', 'ambient/weather/rain1.ogg', 'weather.rain', 'ambient/weather/rain1.ogg'),
    ('item.spyglass.stop', 'item/spyglass/stop.ogg', 'item.spyglass.stop_using', 'item/spyglass/stop.ogg'),
    ('item.brush.brushing', 'item/brush/brushing_generic1.ogg', 'item.brush.brushing.generic', 'item/brush/brushing_generic1.ogg'),
    ('block.enderchest.open', 'block/enderchest/open.ogg', 'block.ender_chest.open', 'block/enderchest/open.ogg'),
    ('block.amethyst.break', 'block/amethyst/break1.ogg', 'block.amethyst_block.break', 'block/amethyst/break1.ogg'),
    ('block.amethyst.resonate', 'block/amethyst/resonate1.ogg', 'block.amethyst_block.resonate', 'block/amethyst/resonate1.ogg'),
    ('entity.villager.haggle', 'mob/villager/haggle1.ogg', 'entity.villager.trade', 'mob/villager/haggle1.ogg'),
    ('entity.axolotl.idle', 'mob/axolotl/idle1.ogg', 'entity.axolotl.idle_water', 'mob/axolotl/idle1.ogg'),
    ('entity.frog.idle', 'mob/frog/idle1.ogg', 'entity.frog.ambient', 'mob/frog/idle1.ogg'),
    ('entity.goat.scream', 'mob/goat/scream1.ogg', 'entity.goat.screaming.ambient', 'mob/goat/scream1.ogg'),
    ('entity.parrot.idle', 'mob/parrot/idle1.ogg', 'entity.parrot.ambient', 'mob/parrot/idle1.ogg'),
    ('entity.strider.idle', 'mob/strider/idle1.ogg', 'entity.strider.ambient', 'mob/strider/idle1.ogg'),
    ('entity.piglin.admire', 'mob/piglin/admire1.ogg', 'entity.piglin.admiring_item', 'mob/piglin/admire1.ogg'),
    ('entity.cat.meow', 'mob/cat/meow1.ogg', 'entity.cat.ambient', 'mob/cat/meow1.ogg'),
    ('entity.player.drink', 'random/drink.ogg', 'entity.generic.drink', 'random/drink.ogg'),
    ('entity.player.eat', 'random/eat1.ogg', 'entity.generic.eat', 'random/eat1.ogg'),
    ('block.end_portal.eyeplace', 'block/end_portal/eyeplace1.ogg', 'block.end_portal_frame.fill', 'block/end_portal/eyeplace1.ogg'),
    ('item.goat_horn.sound', 'item/goat_horn/call0.ogg', 'item.goat_horn.sound.0', 'item/goat_horn/call0.ogg'),
]

# ---------------------------------------------------------
# 4. SALVATAGGIO SU DISCO
# ---------------------------------------------------------
def sound_path_for(sound_info):
    return os.path.join(SOUNDS_DIR, sound_info["file"].replace(".ogg", "") + ".ogg")


def get_saved_sounds_manifest():
    if os.path.exists(SOUNDS_JSON_PATH):
        try:
            with open(SOUNDS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _atomic_write_json(path, data):
    """Scrive su file temporaneo e poi sostituisce."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def is_valid_audio_file(path):
    """File presente, non vuoto e con intestazione OGG valida."""
    try:
        if not os.path.exists(path) or os.path.getsize(path) < 200:
            return False
        with open(path, "rb") as f:
            return f.read(4) == b"OggS"
    except OSError:
        return False


def migrate_legacy_entries():
    """Sposta suoni e voci di sounds.json salvati con vecchi ID/percorsi."""
    with get_write_lock():
        manifest = get_saved_sounds_manifest()
        changed = False
        for old_id, old_file, new_id, new_file in LEGACY_ENTRIES:
            old_key, new_key = old_file.replace(".ogg", ""), new_file.replace(".ogg", "")
            old_path = os.path.join(SOUNDS_DIR, old_key + ".ogg")
            new_path = os.path.join(SOUNDS_DIR, new_key + ".ogg")
            if old_key != new_key and os.path.exists(old_path) and not os.path.exists(new_path):
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                os.replace(old_path, new_path)
            if old_id in manifest and (old_id != new_id or old_key != new_key):
                entry = manifest.pop(old_id)
                entry["sounds"] = [{"name": new_key, "stream": bool(entry.get("sounds", [{}])[0].get("stream", False))}]
                manifest.setdefault(new_id, entry)
                changed = True
        if changed:
            _atomic_write_json(SOUNDS_JSON_PATH, manifest)


def save_sound_realtime(sound_id, sound_file_path, audio_segment, user_name):
    """Salva l'OGG e aggiorna sounds.json."""
    file_key = sound_file_path.replace(".ogg", "")
    target_ogg_path = os.path.join(SOUNDS_DIR, f"{file_key}.ogg")
    tmp_ogg_path = target_ogg_path + ".tmp"

    is_music_track = file_key.startswith("music/")
    is_long = len(audio_segment) >= 10_000

    try:
        os.makedirs(os.path.dirname(target_ogg_path), exist_ok=True)

        if audio_segment.max_dBFS > -1.0:
            audio_segment = audio_segment.apply_gain(-1.0 - audio_segment.max_dBFS)

        channels = 2 if is_music_track else 1
        out = audio_segment.set_channels(channels)
        vorbis_quality = "8" if is_long else "10"

        with get_write_lock():
            out.export(tmp_ogg_path, format="ogg", codec="libvorbis", parameters=["-q:a", vorbis_quality])
            os.replace(tmp_ogg_path, target_ogg_path)

            if not os.path.exists(MCMETA_PATH):
                _atomic_write_json(MCMETA_PATH, {
                    "pack": {
                        "pack_format": 46,
                        "min_format": 15,
                        "max_format": 99,
                        "supported_formats": [15, 99],
                        "description": "Custom Sound Pack - Creato con la community",
                    }
                })

            sounds_data = get_saved_sounds_manifest()
            sounds_data[sound_id] = {
                "replace": True,
                "author": user_name,
                "description": f"Audio personalizzato caricato da {user_name}",
                "sounds": [{"name": file_key, "stream": bool(is_music_track or is_long)}],
            }
            _atomic_write_json(SOUNDS_JSON_PATH, sounds_data)
        return True, ""
    except Exception as e:
        if os.path.exists(tmp_ogg_path):
            try:
                os.remove(tmp_ogg_path)
            except OSError:
                pass
        return False, str(e)

# ---------------------------------------------------------
# 5. INTESTAZIONE & DASHBOARD SUONI COMPLETATI
# ---------------------------------------------------------
st.title("🎵 Minecraft Sound Studio Pro")

flash_msg = st.session_state.pop("flash", None)
if flash_msg:
    st.toast(flash_msg, icon="✅")

migrate_legacy_entries()
saved_manifest = get_saved_sounds_manifest()
checked_manifest = get_checked_sounds()
total_sounds = len(VANILLA_SOUNDS_MAP)

done_map = {}
completed_items = []
for s in VANILLA_SOUNDS_MAP:
    p = sound_path_for(s)
    done = is_valid_audio_file(p) and s["id"] in saved_manifest
    done_map[s["id"]] = done
    if done:
        completed_items.append({
            "label": s["label"],
            "id": s["id"],
            "author": saved_manifest[s["id"]].get("author", "Sconosciuto"),
            "file": p,
        })

completed_count = len(completed_items)
progress_pct = (completed_count / total_sounds) * 100.0 if total_sounds else 0.0

st.sidebar.subheader("📈 Progresso Pacchetto Audio")
st.sidebar.progress(progress_pct / 100.0)
st.sidebar.metric("Suoni Completati", f"{completed_count} / {total_sounds}", f"{progress_pct:.1f}%")

st.sidebar.checkbox(
    "🌐 Modalità compatibilità (Safari / iPhone)",
    key="compat_audio",
    help="Converte le anteprime in MP3 se il browser non riproduce i file .ogg.",
)

st.caption(f"Utente collegato: **{st.session_state['user_name']}** | Salvataggio in tempo reale ⚡")

if st.sidebar.button("🚪 Disconnetti"):
    st.session_state["authenticated"] = False
    st.session_state["user_name"] = ""
    st.rerun()

# --- GALLERY SUONI COMPLETATI ---
GALLERY_MAX = 30
with st.expander(f"🏆 Galleria Suoni Completati ({completed_count}/{total_sounds})", expanded=False):
    if not completed_items:
        st.info("Nessun suono è stato ancora salvato nel pacchetto.")
    else:
        show_players = st.toggle("Mostra i lettori audio", value=False, key="gallery_players")
        grid_cols = st.columns(3)
        for idx, item in enumerate(completed_items):
            with grid_cols[idx % 3]:
                st.markdown(f"**{item['label']}**")
                st.caption(f"Autore: **{item['author']}**")
                if show_players and idx < GALLERY_MAX:
                    show_player(item["file"])
        if show_players and completed_count > GALLERY_MAX:
            st.caption(f"Lettori mostrati solo per i primi {GALLERY_MAX} suoni. Usa il filtro «Solo Completati» per ascoltare gli altri.")

st.divider()

# ---------------------------------------------------------
# 6. FILTRI AVANZATI NEL MENU LATERALE
# ---------------------------------------------------------
st.sidebar.header("🔍 Filtri Avanzati")

search_query = st.sidebar.text_input("Cerca per nome o ID:", "").lower().strip()

selected_cat = st.sidebar.radio(
    "Categoria:",
    ["Tutti i suoni", "⚔️ Combat & Danni", "👾 Mob & Creature", "🧱 Blocchi & Interazioni", "🎵 Ambiente, UI & Dischi"],
)

filter_status = st.sidebar.selectbox(
    "Stato Completamento:",
    ["Tutti", "✅ Solo Completati", "⏳ Non Completati", "🇨🇳 Controllato"],
)

filtered_sounds = []
for s in VANILLA_SOUNDS_MAP:
    is_done = done_map[s["id"]]
    is_checked = checked_manifest.get(s["id"], False)
    if selected_cat != "Tutti i suoni" and s["cat"] != selected_cat:
        continue
    if filter_status == "✅ Solo Completati" and not is_done:
        continue
    if filter_status == "⏳ Non Completati" and is_done:
        continue
    if filter_status == "🇨🇳 Controllato" and not is_checked:
        continue
    if search_query and (search_query not in s["label"].lower() and search_query not in s["id"].lower()):
        continue
    filtered_sounds.append(s)

st.write(f"📊 Suoni Trovati: **{len(filtered_sounds)}**")

# ---------------------------------------------------------
# 7. SCHEDE SUONI & EDITOR DIRETTO
# ---------------------------------------------------------
filter_sig = (search_query, selected_cat, filter_status)
if "visible_count" not in st.session_state or st.session_state.get("filter_sig") != filter_sig:
    st.session_state["visible_count"] = 10
    st.session_state["filter_sig"] = filter_sig

displayed_sounds = filtered_sounds[: st.session_state["visible_count"]]

cols = st.columns(2)

for index, sound_info in enumerate(displayed_sounds):
    col = cols[index % 2]
    sound_id = sound_info["id"]
    custom_saved_file_path = sound_path_for(sound_info)

    is_already_saved = done_map[sound_id]
    saved_author = saved_manifest.get(sound_id, {}).get("author", "Utente Sconosciuto")
    is_checked = checked_manifest.get(sound_id, False)

    version_key = f"v_{sound_id}"
    if version_key not in st.session_state:
        st.session_state[version_key] = 0
    v = st.session_state[version_key]

    confirm_del_key = f"confirm_del_{sound_id}"

    with col:
        with st.container(border=True):
            # INTESTAZIONE CON SPUNTA CONTROLLATO IN ALTO A DESTRA
            head_col1, head_col2 = st.columns([3, 1])
            with head_col1:
                st.markdown(f"### {sound_info['label']}")
            with head_col2:
                chk_val = st.checkbox("Controllato", value=is_checked, key=f"chk_{sound_id}")
                if chk_val != is_checked:
                    set_sound_checked(sound_id, chk_val)
                    st.rerun()

            st.caption(f"🆔 ID Minecraft: `{sound_id}`")

            # --- SUONO ORIGINALE ---
            found_orig_path = find_original_sound_file(ORIGINAL_SOUNDS_DIR, sound_info["file"])
            st.markdown("**🔊 Suono Originale Minecraft:**")
            if found_orig_path:
                show_player(found_orig_path)
            else:
                st.info(f"💡 File non trovato in `{os.path.join(ORIGINAL_SOUNDS_DIR, sound_info['file'])}`")

            st.divider()

            # --- AUDIO PERSONALIZZATO ---
            if is_already_saved:
                st.success(f"🟢 **Audio Presente** (Autore: **{saved_author}**)")
                show_player(custom_saved_file_path)

                # PULSANTE E CONFERMA ELIMINAZIONE
                del_col1, del_col2 = st.columns([2, 1])
                with del_col2:
                    if is_checked:
                        st.button("🗑️ Elimina", key=f"del_{sound_id}", disabled=True, help="Rimuovi la spunta 'Controllato' per eliminare questo audio")
                    else:
                        if not st.session_state.get(confirm_del_key, False):
                            if st.button("🗑️ Elimina Audio", key=f"del_{sound_id}", type="secondary"):
                                st.session_state[confirm_del_key] = True
                                st.rerun()

                # BOX DI CONFERMA ELIMINAZIONE
                if st.session_state.get(confirm_del_key, False) and not is_checked:
                    st.warning("⚠️ **Sei sicuro di voler eliminare questo audio?** L'azione non è reversibile.")
                    c_col1, c_col2 = st.columns(2)
                    with c_col1:
                        if st.button("⚠️ Sì, elimina definitivamente", key=f"yes_del_{sound_id}", type="primary", use_container_width=True):
                            delete_sound_realtime(sound_id, sound_info["file"])
                            st.session_state[confirm_del_key] = False
                            st.session_state["flash"] = f"Eliminato l'audio «{sound_info['label']}»"
                            st.rerun()
                    with c_col2:
                        if st.button("Annulla", key=f"no_del_{sound_id}", use_container_width=True):
                            st.session_state[confirm_del_key] = False
                            st.rerun()

                st.markdown("**🔄 Sostituisci Audio:**")
            else:
                st.markdown("**📤 Carica File o Registra dal Microfono:**")

            # 1. Caricamento File
            uploaded_file = st.file_uploader(
                "Carica File Audio",
                type=["mp3", "wav", "ogg", "m4a", "flac"],
                key=f"file_{sound_id}_{v}",
                label_visibility="collapsed",
            )

            # 2. Registratore Microfono Diretto
            recorded_audio = None
            if hasattr(st, "audio_input"):
                try:
                    recorded_audio = st.audio_input(
                        "🎙️ Registra Microfono", key=f"rec_{sound_id}_{v}", sample_rate=48000
                    )
                except TypeError:
                    recorded_audio = st.audio_input("🎙️ Registra Microfono", key=f"rec_{sound_id}_{v}")
                    st.caption("⚠️ Aggiorna Streamlit (`pip install -U streamlit`) per registrare a qualità piena.")
            else:
                st.caption("🎙️ Registrazione non disponibile: aggiorna Streamlit (`pip install -U streamlit`).")

            candidate_file = uploaded_file or recorded_audio
            from_mic = candidate_file is not None and candidate_file is recorded_audio and uploaded_file is None

            # --- EDITOR AUDIO ---
            if candidate_file is not None:
                st.markdown("---")
                st.markdown("### ✂️ Editor Audio")

                try:
                    file_bytes = candidate_file.getvalue()
                    if not file_bytes:
                        raise ValueError("il file è vuoto")
                    file_id = hashlib.md5(file_bytes).hexdigest()[:8]
                    raw_audio = decode_audio(file_bytes)

                    if from_mic:
                        cut_click = st.checkbox(
                            "Rimuovi il click iniziale del mouse (primi 350 ms)",
                            value=True,
                            key=f"click_{sound_id}_{v}_{file_id}",
                        )
                        if cut_click and len(raw_audio) > 400:
                            raw_audio = raw_audio[350:]

                    total_duration_sec = round(len(raw_audio) / 1000.0, 2)

                    if total_duration_sec >= 0.1:
                        trim_range = st.slider(
                            "Mantiene l'audio tra (secondi):",
                            min_value=0.0,
                            max_value=total_duration_sec,
                            value=(0.0, total_duration_sec),
                            step=0.05,
                            key=f"slider_{sound_id}_{v}_{file_id}_{from_mic}",
                        )
                        vol_gain = st.slider("🔊 Regola Volume (dB):", -12, 12, 0, key=f"gain_{sound_id}_{v}")

                        start_ms = int(trim_range[0] * 1000)
                        end_ms = int(trim_range[1] * 1000)

                        if end_ms - start_ms < 100:
                            st.error("L'intervallo selezionato è troppo corto (minimo 0,1 s).")
                        else:
                            edited_audio = raw_audio[start_ms:end_ms].apply_gain(vol_gain)

                            buf = io.BytesIO()
                            if len(edited_audio) < 30_000:
                                edited_audio.export(buf, format="wav")
                                preview_mime = "audio/wav"
                            else:
                                edited_audio.export(buf, format="mp3", bitrate="128k")
                                preview_mime = "audio/mpeg"

                            st.warning("🎧 **Anteprima Audio Modificato:**")
                            st.audio(buf.getvalue(), format=preview_mime)

                            btn_col1, btn_col2 = st.columns(2)
                            with btn_col1:
                                if st.button("✅ Conferma e Salva", key=f"save_{sound_id}_{v}", type="primary", use_container_width=True):
                                    ok, err = save_sound_realtime(
                                        sound_id, sound_info["file"], edited_audio, st.session_state["user_name"]
                                    )
                                    if ok:
                                        st.session_state[version_key] += 1
                                        st.session_state["flash"] = (
                                            f"Salvato «{sound_info['label']}» da {st.session_state['user_name']}!"
                                        )
                                        st.rerun()
                                    else:
                                        st.error(f"Errore salvataggio: {err}")
                            with btn_col2:
                                if st.button("❌ Annulla / Scarta", key=f"cancel_{sound_id}_{v}", use_container_width=True):
                                    st.session_state[version_key] += 1
                                    st.rerun()
                    else:
                        st.error("Audio troppo corto o non valido.")
                except Exception as err:
                    st.error(f"Errore elaborazione audio: {err}")

# --- CARICA ALTRI SUONI ---
if len(displayed_sounds) < len(filtered_sounds):
    st.divider()
    if st.button("👇 Carica altri suoni...", use_container_width=True, type="secondary"):
        st.session_state["visible_count"] += 10
        st.rerun()