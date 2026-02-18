import discord
import os
import json
import hashlib
import logging
from pathlib import Path
from dotenv import load_dotenv
import datetime
import re

load_dotenv()

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("antitrigger")

# --- CONFIGURAÇÃO (valores padrão, podem ser sobrescritos pelo .env) ---
def _parse_channel_ids(env_var: str, default: list) -> list:
    """Converte variável de ambiente (IDs separados por vírgula) em lista de int."""
    val = os.getenv(env_var)
    if val:
        try:
            return [int(x.strip()) for x in val.split(",") if x.strip()]
        except ValueError:
            pass
    return default

TOKEN = os.getenv("TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID", "1398496668537716896"))
ALERT_CHANNELS = _parse_channel_ids("ALERT_CHANNELS", [1387430519582494883, 1421954201969496158])
SALARY_DUMP_ALERT_CHANNELS = _parse_channel_ids("SALARY_DUMP_ALERT_CHANNELS", [1471831384837460136])
SALARY_LEGIT_ALERT_CHANNELS = _parse_channel_ids("SALARY_LEGIT_ALERT_CHANNELS", [1473755075670310942])

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)

# --- MEMÓRIA DO BOT ---
log_history = {}
alerted_logs = {}
alerted_salary_chains = {}  # citizenid -> {"chain": tuple, "timestamp": datetime}
alerted_salary_legit_chains = {}

# --- PARÂMETROS ---
TIME_WINDOW_SECONDS = int(os.getenv("TIME_WINDOW_SECONDS", "60"))
LOG_COUNT_THRESHOLD = int(os.getenv("LOG_COUNT_THRESHOLD", "3"))
SALARY_DUMP_VALUES = {3000, 5000, 7000, 9000}
SALARY_LOG_FILE = Path(__file__).parent / "salary_logs.json"
SALARY_LEGIT_LOG_FILE = Path(__file__).parent / "salary_legit_logs.json"
SPAM_LOG_FILE = Path(__file__).parent / "spam_logs.json"
SPAM_LOG_RETENTION = 2 * 60 * 60
SALARY_INTERVAL_MIN = 25 * 60
SALARY_INTERVAL_MAX = 35 * 60
SALARY_LOG_RETENTION = 2 * 60 * 60
DISCORD_MESSAGE_LIMIT = 2000

# --- REGEX COMPILADOS ---
RE_TECHO = re.compile(r"(\*\*.*?added)")
RE_RHIS5UDIE = re.compile(r"rhis5udie(_dlc)?")
RE_CITIZENID = re.compile(r"citizenid:\s*([A-Z0-9]+)", re.IGNORECASE)
RE_REASON = re.compile(r"reason:\s*([^\n*]+)", re.IGNORECASE)
RE_VALOR = re.compile(r"\$(\d+)")

REASONS_SALARIO_LEGITIMOS = ("salario comprado", "salario vip")


def parse_timestamp(ts_str: str):
    """Converte string ISO para datetime (timezone-aware)."""
    return datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def truncar_mensagem(texto: str, limite: int = DISCORD_MESSAGE_LIMIT) -> str:
    """Trunca mensagem se exceder limite do Discord, preservando o início."""
    if len(texto) <= limite:
        return texto
    return texto[: limite - 50] + "\n\n... (mensagem truncada)"


def extrair_trecho(texto):
    match = RE_TECHO.search(texto)
    return match.group(1) if match else None


def substituir_rhis5udie_por_vip(texto):
    return RE_RHIS5UDIE.sub(r"vip\1", texto)


def extrair_citizenid(texto):
    match = RE_CITIZENID.search(texto)
    return match.group(1) if match else None


def extrair_tipo_dinheiro(texto):
    texto_lower = texto.lower()
    if "(bank)" in texto_lower:
        return "bank"
    if "(cash)" in texto_lower:
        return "cash"
    return None


def carregar_salary_logs():
    try:
        if SALARY_LOG_FILE.exists():
            with open(SALARY_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {}


def salvar_salary_logs(data):
    try:
        with open(SALARY_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error("Erro ao salvar salary_logs.json: %s", e)


def carregar_salary_legit_logs():
    try:
        if SALARY_LEGIT_LOG_FILE.exists():
            with open(SALARY_LEGIT_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {}


def salvar_salary_legit_logs(data):
    try:
        with open(SALARY_LEGIT_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error("Erro ao salvar salary_legit_logs.json: %s", e)


def spam_log_key_hash(log_key):
    return hashlib.md5(log_key.encode("utf-8")).hexdigest()[:24]


def carregar_spam_logs():
    try:
        if SPAM_LOG_FILE.exists():
            with open(SPAM_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {}


def salvar_spam_logs(data):
    try:
        with open(SPAM_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error("Erro ao salvar spam_logs.json: %s", e)


def limpar_chains_antigos(chains_dict, max_age_seconds=SALARY_LOG_RETENTION):
    """Remove entradas antigas dos dicionários de chains alertadas."""
    now = datetime.datetime.now()
    for key in list(chains_dict.keys()):
        entry = chains_dict[key]
        if isinstance(entry, dict) and "timestamp" in entry:
            if (now - entry["timestamp"]).total_seconds() >= max_age_seconds:
                del chains_dict[key]


def encontrar_cadeia_30min(entries):
    if len(entries) < 2:
        return []
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(seconds=SALARY_LOG_RETENTION)
    valid = []
    for e in entries:
        try:
            ts = parse_timestamp(e["timestamp"])
            if ts > cutoff:
                valid.append((ts, e))
        except (ValueError, KeyError):
            continue
    valid.sort(key=lambda x: x[0])
    best_chain = []
    for i in range(len(valid)):
        chain = [valid[i][1]]
        last_ts = valid[i][0]
        for j in range(i + 1, len(valid)):
            delta = (valid[j][0] - last_ts).total_seconds()
            if SALARY_INTERVAL_MIN <= delta <= SALARY_INTERVAL_MAX:
                chain.append(valid[j][1])
                last_ts = valid[j][0]
            else:
                break
        if len(chain) >= 2 and len(chain) > len(best_chain):
            best_chain = chain
    return best_chain


def verificar_dump_salario(texto, trecho):
    tipo = extrair_tipo_dinheiro(texto)
    if tipo is None:
        return False, None, None, None
    match_reason = RE_REASON.search(texto)
    reason_extraido = match_reason.group(1).strip() if match_reason else "não encontrado"
    if match_reason:
        if reason_extraido.lower() in REASONS_SALARIO_LEGITIMOS:
            return False, None, None, None
    match = RE_VALOR.search(texto)
    if not match:
        return False, None, None, None
    valor = int(match.group(1))
    if valor not in SALARY_DUMP_VALUES:
        return False, None, None, None
    return True, valor, reason_extraido, tipo


def verificar_salario_legitimo(texto, trecho):
    tipo = extrair_tipo_dinheiro(texto)
    if tipo is None:
        return False, None, None, None
    match_reason = RE_REASON.search(texto)
    reason_extraido = match_reason.group(1).strip() if match_reason else ""
    if not match_reason or reason_extraido.lower() not in REASONS_SALARIO_LEGITIMOS:
        return False, None, None, None
    match = RE_VALOR.search(texto)
    if not match:
        return False, None, None, None
    valor = int(match.group(1))
    if valor not in SALARY_DUMP_VALUES:
        return False, None, None, None
    return True, valor, reason_extraido, tipo


async def enviar_alerta(canal_id, mensagem, tipo="alerta"):
    """Envia mensagem ao canal com tratamento de erros e limite de caracteres."""
    try:
        channel = client.get_channel(canal_id)
        if not channel:
            logger.warning("Canal não encontrado: %s", canal_id)
            return False
        msg_final = truncar_mensagem(mensagem)
        await channel.send(msg_final)
        logger.info("%s enviado para canal %s", tipo, canal_id)
        return True
    except discord.HTTPException as e:
        logger.error("Erro HTTP ao enviar para canal %s: %s", canal_id, e)
    except discord.Forbidden:
        logger.error("Sem permissão para enviar no canal %s", canal_id)
    except Exception as e:
        logger.exception("Erro inesperado ao enviar alerta: %s", e)
    return False


@client.event
async def on_ready():
    logger.info("🤖 Bot Anti Trigger SCC conectado como %s", client.user)
    logger.info("🎯 Canal monitorado: %s", TARGET_CHANNEL_ID)
    logger.info("⏰ Spam: %s logs em %ss", LOG_COUNT_THRESHOLD, TIME_WINDOW_SECONDS)
    logger.info("📁 Spam: %s | Dump: 1471831384837460136 | Legítimo: 1473755075670310942", SPAM_LOG_FILE.name)
    logger.info("✅ Bot online e monitorando...")


@client.event
async def on_message(message):
    if message.author == client.user or message.channel.id != TARGET_CHANNEL_ID:
        return

    texto_completo = ""
    if message.embeds:
        for embed in message.embeds:
            if embed.title:
                texto_completo += embed.title
            if embed.description:
                texto_completo += embed.description

    texto_lower = texto_completo.lower()

    if "addmoney" not in texto_lower or "citizenid" not in texto_lower or "id" not in texto_lower or "added" not in texto_lower:
        return

    now = datetime.datetime.now()
    trecho = extrair_trecho(texto_completo)
    if not trecho:
        return
    log_key = trecho

    # --- ALERTA: Dump de Salário ---
    é_dump, valor, reason, tipo = verificar_dump_salario(texto_completo, trecho)
    if é_dump:
        citizenid = extrair_citizenid(texto_completo)
        if citizenid:
            logs = carregar_salary_logs()
            if citizenid not in logs:
                logs[citizenid] = []
            logs[citizenid].append({
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "value": valor,
                "reason": reason,
                "type": tipo,
            })
            cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=SALARY_LOG_RETENTION)
            logs[citizenid] = [e for e in logs[citizenid] if parse_timestamp(e["timestamp"]) > cutoff]
            salvar_salary_logs(logs)
            cadeia_logs = encontrar_cadeia_30min(logs[citizenid])
            if cadeia_logs:
                limpar_chains_antigos(alerted_salary_chains)
                chain_key = tuple(e["timestamp"] for e in cadeia_logs)
                ultima = alerted_salary_chains.get(citizenid)
                ultima_chain = ultima.get("chain") if isinstance(ultima, dict) else ultima
                if not (ultima_chain == chain_key):
                    alerted_salary_chains[citizenid] = {"chain": chain_key, "timestamp": now}
                    trecho_mod = substituir_rhis5udie_por_vip(trecho)
                    logs_texto = "\n".join(
                        f"  {i + 1}. ${e['value']} ({e.get('type', 'bank')}) - reason: {e['reason']} | {parse_timestamp(e['timestamp']).strftime('%d-%m-%Y %H:%M:%S')}"
                        for i, e in enumerate(cadeia_logs)
                    )
                    alert_interval = (
                        f"@everyone ⚠️ SALÁRIO SEM REASON EM INTERVALOS DE ~30 MIN!\n"
                        f"{trecho_mod}\n"
                        f"CitizenID: {citizenid} - {len(cadeia_logs)} logs em ~30 min sem reason correto\n\n"
                        f"**Logs detectados no intervalo:**\n{logs_texto}"
                    )
                    for cid in SALARY_DUMP_ALERT_CHANNELS:
                        await enviar_alerta(cid, alert_interval, "Alerta Dump 30min")

    # --- ALERTA: Salário Legítimo ---
    é_legit, valor_legit, reason_legit, tipo_legit = verificar_salario_legitimo(texto_completo, trecho)
    if é_legit:
        citizenid = extrair_citizenid(texto_completo)
        if citizenid:
            logs = carregar_salary_legit_logs()
            if citizenid not in logs:
                logs[citizenid] = []
            logs[citizenid].append({
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "value": valor_legit,
                "reason": reason_legit,
                "type": tipo_legit,
            })
            cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=SALARY_LOG_RETENTION)
            logs[citizenid] = [e for e in logs[citizenid] if parse_timestamp(e["timestamp"]) > cutoff]
            salvar_salary_legit_logs(logs)
            cadeia_logs = encontrar_cadeia_30min(logs[citizenid])
            if cadeia_logs:
                limpar_chains_antigos(alerted_salary_legit_chains)
                chain_key = tuple(e["timestamp"] for e in cadeia_logs)
                ultima = alerted_salary_legit_chains.get(citizenid)
                ultima_chain = ultima.get("chain") if isinstance(ultima, dict) else ultima
                if not (ultima_chain == chain_key):
                    alerted_salary_legit_chains[citizenid] = {"chain": chain_key, "timestamp": now}
                    trecho_mod = substituir_rhis5udie_por_vip(trecho)
                    logs_texto = "\n".join(
                        f"  {i + 1}. ${e['value']} ({e.get('type', 'bank')}) - reason: {e['reason']} | {parse_timestamp(e['timestamp']).strftime('%d-%m-%Y %H:%M:%S')}"
                        for i, e in enumerate(cadeia_logs)
                    )
                    alert_legit = (
                        f"@everyone ✅ SALÁRIO LEGÍTIMO EM INTERVALOS DE ~30 MIN\n"
                        f"{trecho_mod}\n"
                        f"CitizenID: {citizenid} - {len(cadeia_logs)} logs em ~30 min (reason correto)\n\n"
                        f"**Logs detectados:**\n{logs_texto}"
                    )
                    for cid in SALARY_LEGIT_ALERT_CHANNELS:
                        await enviar_alerta(cid, alert_legit, "Alerta Salário Legítimo")

    # --- Spam ---
    for key in list(log_history.keys()):
        valid = [ts for ts in log_history[key] if (now - ts).total_seconds() < TIME_WINDOW_SECONDS]
        if not valid:
            del log_history[key]
        else:
            log_history[key] = valid

    for key in list(alerted_logs.keys()):
        if (now - alerted_logs[key]).total_seconds() >= TIME_WINDOW_SECONDS:
            del alerted_logs[key]

    if log_key in alerted_logs:
        return

    if log_key not in log_history:
        log_history[log_key] = []
    log_history[log_key].append(now)

    spam_data = carregar_spam_logs()
    key_hash = spam_log_key_hash(log_key)
    if key_hash not in spam_data:
        spam_data[key_hash] = {"trecho": log_key, "logs": []}
    spam_data[key_hash]["logs"].append({"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    spam_data[key_hash]["trecho"] = log_key
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=SPAM_LOG_RETENTION)
    spam_data[key_hash]["logs"] = [e for e in spam_data[key_hash]["logs"] if parse_timestamp(e["timestamp"]) > cutoff]
    salvar_spam_logs(spam_data)

    log_count = len(log_history[log_key])
    logger.debug("AddMoney detectado. Chave: '%s...'. Contagem: %s/%s", log_key[:30], log_count, LOG_COUNT_THRESHOLD)

    if log_count == LOG_COUNT_THRESHOLD:
        logger.info("!!! ALERTA DE SPAM !!! Chave: %s", log_key[:50])
        alerted_logs[log_key] = now

        match_reason = RE_REASON.search(texto_completo)
        reason = match_reason.group(1).strip().lower() if match_reason else ""
        pular_alerta_salario = reason in REASONS_SALARIO_LEGITIMOS

        if not pular_alerta_salario:
            log_key_modificado = substituir_rhis5udie_por_vip(log_key)
            spam_data = carregar_spam_logs()
            all_logs = spam_data.get(key_hash, {}).get("logs", [])
            cutoff_spam = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=SPAM_LOG_RETENTION)
            all_logs = [e for e in all_logs if parse_timestamp(e["timestamp"]) > cutoff_spam]
            all_logs.sort(key=lambda e: e["timestamp"])
            spam_data[key_hash] = {"trecho": log_key, "logs": all_logs}
            salvar_spam_logs(spam_data)
            logs_texto = "\n".join(
                f"  {i + 1}. {parse_timestamp(e['timestamp']).strftime('%d-%m-%Y %H:%M:%S')}"
                for i, e in enumerate(all_logs)
            )
            alert_message = (
                f"@everyone ALERTA DE SPAM DETECTADO!\n"
                f"{log_key_modificado}\n"
                f"LOG SUSPEITO DETECTADO 🧑🏻‍🎄\n\n"
                f"**Logs acumulados ({len(all_logs)} total, janela {SPAM_LOG_RETENTION // 3600}h):**\n{logs_texto}"
            )
            for cid in ALERT_CHANNELS:
                await enviar_alerta(cid, alert_message, "Alerta Spam")
        else:
            logger.info("Alerta spam ignorado - reason legítimo: %s", reason)

        if log_key in log_history:
            del log_history[log_key]


if __name__ == "__main__":
    if not TOKEN:
        logger.error("TOKEN não encontrado! Configure a variável TOKEN no arquivo .env")
        exit(1)
    client.run(TOKEN)
