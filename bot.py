import discord
import os
import json
import hashlib
import logging
import asyncio
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
spam_lock = asyncio.Lock()
spam_memory = {}  # key_hash -> {"logs": [...], "trecho": str} - cache em memória para acumular

# --- PARÂMETROS ---
TIME_WINDOW_SECONDS = int(os.getenv("TIME_WINDOW_SECONDS", "60"))
LOG_COUNT_THRESHOLD = int(os.getenv("LOG_COUNT_THRESHOLD", "3"))
SALARY_DUMP_VALUES = {3000, 5000, 7000, 9000}
SALARY_LOG_FILE = Path(__file__).parent / "salary_logs.json"
SALARY_LEGIT_LOG_FILE = Path(__file__).parent / "salary_legit_logs.json"
SPAM_LOG_FILE = Path(__file__).parent / "spam_logs.json"
SPAM_ALERTS_FILE = Path(__file__).parent / "spam_alerts.json"
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
RE_TIMESTAMP_LOG = re.compile(r"(\d{1,2}:\d{2}:\d{2}\s+\d{2}-\d{2}-\d{4})")

REASONS_SALARIO_LEGITIMOS = ("salario comprado", "salario vip")

ORDINAIS = (
    "PRIMEIRO", "SEGUNDO", "TERCEIRO", "QUARTO", "QUINTO", "SEXTO", "SÉTIMO",
    "OITAVO", "NONO", "DÉCIMO", "DÉCIMO PRIMEIRO", "DÉCIMO SEGUNDO", "DÉCIMO TERCEIRO",
    "DÉCIMO QUARTO", "DÉCIMO QUINTO", "DÉCIMO SEXTO", "DÉCIMO SÉTIMO", "DÉCIMO OITAVO",
    "DÉCIMO NONO", "VIGÉSIMO", "VIGÉSIMO PRIMEIRO", "VIGÉSIMO SEGUNDO", "VIGÉSIMO TERCEIRO",
    "VIGÉSIMO QUARTO", "VIGÉSIMO QUINTO", "VIGÉSIMO SEXTO", "VIGÉSIMO SÉTIMO",
    "VIGÉSIMO OITAVO", "VIGÉSIMO NONO", "TRIGÉSIMO",
)


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


def extrair_timestamp_da_log(texto):
    """
    Extrai o horário da log (ex: 13:27:38 02-18-2026) do texto da mensagem.
    Retorna (display_str, iso_str) para exibição e ordenação, ou (None, None) se não encontrar.
    Formato da log: HH:MM:SS MM-DD-YYYY ou HH:MM:SS DD-MM-YYYY
    """
    match = RE_TIMESTAMP_LOG.search(texto)
    if not match:
        return None, None
    ts_str = match.group(1).strip()
    for fmt in ("%H:%M:%S %m-%d-%Y", "%H:%M:%S %d-%m-%Y"):
        try:
            dt = datetime.datetime.strptime(ts_str, fmt).replace(tzinfo=datetime.timezone.utc)
            display = dt.strftime("%d-%m-%Y %H:%M:%S")
            iso_str = dt.isoformat()
            return display, iso_str
        except ValueError:
            continue
    return ts_str, ts_str


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


def carregar_spam_alerts():
    """Carrega spam_alerts.json: { hour_N: { citizenid: { count, last_log } } }"""
    try:
        if SPAM_ALERTS_FILE.exists():
            with open(SPAM_ALERTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {}


def salvar_spam_alerts(data):
    try:
        with open(SPAM_ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error("Erro ao salvar spam_alerts.json: %s", e)


def ordinal_ordem(n):
    """Retorna ordinal em português: 1 -> PRIMEIRO, 2 -> SEGUNDO, etc."""
    if 1 <= n <= len(ORDINAIS):
        return ORDINAIS[n - 1]
    return f"{n}º"


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


async def enviar_alerta_dump_embed(canal_id, trecho_mod, citizenid, cadeia_logs, tipo="Alerta Dump"):
    """Envia alerta de dump de salário em embed."""
    try:
        channel = client.get_channel(canal_id)
        if not channel:
            logger.warning("Canal não encontrado: %s", canal_id)
            return False
        def fmt(e):
            c = e.get("content", "")
            return c.strip() if c else f"${e.get('value')} ({e.get('type', 'bank')}) - {e.get('reason', '')}"
        logs_texto = "\n\n---\n\n".join(fmt(e) for e in cadeia_logs)
        logs_trunc = logs_texto[:4000] + "..." if len(logs_texto) > 4000 else logs_texto
        embed = discord.Embed(
            title="⚠️ SALÁRIO SEM REASON — ~30 MIN",
            description=logs_trunc,
            color=0xE74C3C,
        )
        embed.add_field(name="CitizenID", value=citizenid, inline=True)
        embed.add_field(name="Logs", value=str(len(cadeia_logs)), inline=True)
        embed.set_footer(text=trecho_mod[:100] if len(trecho_mod) > 100 else trecho_mod)
        await channel.send(content="@everyone", embed=embed)
        logger.info("%s enviado para canal %s", tipo, canal_id)
        return True
    except (discord.HTTPException, discord.Forbidden) as e:
        logger.error("Erro ao enviar embed dump: %s", e)
    except Exception as e:
        logger.exception("Erro inesperado: %s", e)
    return False


async def enviar_alerta_legit_embed(canal_id, trecho_mod, citizenid, cadeia_logs, tipo="Alerta Legítimo"):
    """Envia alerta de salário legítimo em embed."""
    try:
        channel = client.get_channel(canal_id)
        if not channel:
            logger.warning("Canal não encontrado: %s", canal_id)
            return False
        def fmt(e):
            c = e.get("content", "")
            return c.strip() if c else f"${e.get('value')} ({e.get('type', 'bank')}) - {e.get('reason', '')}"
        logs_texto = "\n\n---\n\n".join(fmt(e) for e in cadeia_logs)
        logs_trunc = logs_texto[:4000] + "..." if len(logs_texto) > 4000 else logs_texto
        embed = discord.Embed(
            title="✅ SALÁRIO LEGÍTIMO — ~30 MIN",
            description=logs_trunc,
            color=0x27AE60,
        )
        embed.add_field(name="CitizenID", value=citizenid, inline=True)
        embed.add_field(name="Logs", value=str(len(cadeia_logs)), inline=True)
        embed.set_footer(text=trecho_mod[:100] if len(trecho_mod) > 100 else trecho_mod)
        await channel.send(content="@everyone", embed=embed)
        logger.info("%s enviado para canal %s", tipo, canal_id)
        return True
    except (discord.HTTPException, discord.Forbidden) as e:
        logger.error("Erro ao enviar embed legit: %s", e)
    except Exception as e:
        logger.exception("Erro inesperado: %s", e)
    return False


async def enviar_alerta_spam_embed(canal_id, log_exibir, count, hora_atual, tipo="Alerta Spam"):
    """Envia alerta de spam em embed minimalista."""
    try:
        channel = client.get_channel(canal_id)
        if not channel:
            logger.warning("Canal não encontrado: %s", canal_id)
            return False
        log_trunc = log_exibir[:4000] + "..." if len(log_exibir) > 4000 else log_exibir
        embed = discord.Embed(
            title=f"🚨 SPAM DETECTADO — {count}x",
            description=log_trunc,
            color=0xE67E22,
        )
        embed.set_footer(text=f"Alertado {count}x na hora {hora_atual}  •  SUSPEITO 🧑🏻‍🎄")
        await channel.send(content="@everyone", embed=embed)
        logger.info("%s enviado para canal %s", tipo, canal_id)
        return True
    except discord.HTTPException as e:
        logger.error("Erro HTTP ao enviar embed spam para canal %s: %s", canal_id, e)
    except discord.Forbidden:
        logger.error("Sem permissão para enviar no canal %s", canal_id)
    except Exception as e:
        logger.exception("Erro inesperado ao enviar alerta spam: %s", e)
    return False


@client.event
async def on_ready():
    logger.info("🤖 Bot Anti Trigger SCC conectado como %s", client.user)
    logger.info("🎯 Canal monitorado: %s", TARGET_CHANNEL_ID)
    logger.info("⏰ Spam: %s logs em %ss", LOG_COUNT_THRESHOLD, TIME_WINDOW_SECONDS)
    logger.info("📁 Spam: %s | Alertas: %s | Dump: 1471831384837460136 | Legítimo: 1473755075670310942", SPAM_LOG_FILE.name, SPAM_ALERTS_FILE.name)
    logger.info("✅ Bot online e monitorando...")


def _build_texto_embed(embed):
    """Monta texto completo a partir de um embed."""
    parts = []
    if embed.title:
        parts.append(embed.title)
    if embed.description:
        parts.append(embed.description)
    if embed.footer and embed.footer.text:
        parts.append(embed.footer.text)
    for field in getattr(embed, "fields", []) or []:
        if field.name:
            parts.append(field.name)
        if field.value:
            parts.append(field.value)
    return "\n".join(parts)


def _extrair_logs_da_mensagem(message):
    """Extrai lista de textos completos (uma por embed ou message.content)."""
    logs = []
    if message.embeds:
        for embed in message.embeds:
            txt = _build_texto_embed(embed)
            if txt and ("addmoney" in txt.lower() and "citizenid" in txt.lower() and "added" in txt.lower()):
                logs.append(txt)
    if not logs and message.content and "addmoney" in message.content.lower() and "citizenid" in message.content.lower():
        logs.append(message.content)
    return logs if logs else None


@client.event
async def on_message(message):
    if message.author == client.user or message.channel.id != TARGET_CHANNEL_ID:
        return

    logs_texto = _extrair_logs_da_mensagem(message)
    if not logs_texto:
        return

    now = datetime.datetime.now()

    for texto_completo in logs_texto:
        trecho = extrair_trecho(texto_completo)
        if not trecho:
            continue
        citizenid = extrair_citizenid(texto_completo)
        spam_key = citizenid if citizenid else trecho

        # --- ALERTA: Dump de Salário ---
        é_dump, valor, reason, tipo = verificar_dump_salario(texto_completo, trecho)
        if é_dump and citizenid:
            logs = carregar_salary_logs()
            if citizenid not in logs:
                logs[citizenid] = []
            ts_display, ts_iso = extrair_timestamp_da_log(texto_completo)
            ts_salary = ts_iso if ts_iso else datetime.datetime.now(datetime.timezone.utc).isoformat()
            logs[citizenid].append({
                "timestamp": ts_salary,
                "value": valor,
                "reason": reason,
                "type": tipo,
                "content": texto_completo,
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
                    for cid in SALARY_DUMP_ALERT_CHANNELS:
                        await enviar_alerta_dump_embed(cid, trecho_mod, citizenid, cadeia_logs)

        # --- ALERTA: Salário Legítimo ---
        é_legit, valor_legit, reason_legit, tipo_legit = verificar_salario_legitimo(texto_completo, trecho)
        if é_legit and citizenid:
            logs = carregar_salary_legit_logs()
            if citizenid not in logs:
                logs[citizenid] = []
            ts_display_legit, ts_iso_legit = extrair_timestamp_da_log(texto_completo)
            ts_salary_legit = ts_iso_legit if ts_iso_legit else datetime.datetime.now(datetime.timezone.utc).isoformat()
            logs[citizenid].append({
                "timestamp": ts_salary_legit,
                "value": valor_legit,
                "reason": reason_legit,
                "type": tipo_legit,
                "content": texto_completo,
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
                    for cid in SALARY_LEGIT_ALERT_CHANNELS:
                        await enviar_alerta_legit_embed(cid, trecho_mod, citizenid, cadeia_logs)

        # --- Spam ---
        async with spam_lock:
            for key in list(log_history.keys()):
                valid = [ts for ts in log_history[key] if (now - ts).total_seconds() < TIME_WINDOW_SECONDS]
                if not valid:
                    del log_history[key]
                else:
                    log_history[key] = valid

            for key in list(alerted_logs.keys()):
                if (now - alerted_logs[key]).total_seconds() >= TIME_WINDOW_SECONDS:
                    del alerted_logs[key]

            if spam_key in alerted_logs:
                continue

            if spam_key not in log_history:
                log_history[spam_key] = []
            log_history[spam_key].append(now)

            key_hash = spam_log_key_hash(spam_key)
            cutoff_load = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=SPAM_LOG_RETENTION)
            if key_hash not in spam_memory:
                disk_data = carregar_spam_logs()
                existing = disk_data.get(key_hash, {}).get("logs", [])
                try:
                    existing = [e for e in existing if parse_timestamp(e.get("timestamp", "")) > cutoff_load]
                except (ValueError, TypeError):
                    existing = []
                spam_memory[key_hash] = {"trecho": trecho, "logs": list(existing)}
            ts_display, ts_iso = extrair_timestamp_da_log(texto_completo)
            ts_armazenar = ts_iso if ts_iso else datetime.datetime.now(datetime.timezone.utc).isoformat()
            spam_memory[key_hash]["logs"].append({
                "timestamp": ts_armazenar,
                "display": ts_display,
                "content": texto_completo,
            })
            spam_memory[key_hash]["trecho"] = trecho
            logs_para_alerta = list(spam_memory[key_hash]["logs"])
            cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=SPAM_LOG_RETENTION)
            try:
                spam_memory[key_hash]["logs"] = [e for e in spam_memory[key_hash]["logs"] if parse_timestamp(e.get("timestamp", "")) > cutoff]
            except (ValueError, TypeError):
                spam_memory[key_hash]["logs"] = [e for e in spam_memory[key_hash]["logs"] if e.get("timestamp")]
            spam_data_persist = {k: {"trecho": v["trecho"], "logs": v["logs"]} for k, v in spam_memory.items()}
            salvar_spam_logs(spam_data_persist)

            log_count = len(log_history[spam_key])
            logger.info("AddMoney detectado. Chave: '%s'. Contagem: %s/%s", spam_key, log_count, LOG_COUNT_THRESHOLD)

            if log_count == LOG_COUNT_THRESHOLD:
                logger.info("!!! ALERTA DE SPAM !!! Chave: %s", spam_key)
                alerted_logs[spam_key] = now

                match_reason = RE_REASON.search(texto_completo)
                reason = match_reason.group(1).strip().lower() if match_reason else ""
                pular_alerta_salario = reason in REASONS_SALARIO_LEGITIMOS

                if not pular_alerta_salario and citizenid:
                    all_logs = logs_para_alerta if logs_para_alerta else [{"content": texto_completo}]
                    all_logs.sort(key=lambda e: e.get("timestamp", ""))
                    log_exibir = all_logs[-1].get("content", texto_completo).strip()

                    hora_atual = now.hour + 1
                    if hora_atual > 24:
                        hora_atual = 1
                    hour_key = f"hour_{hora_atual}"

                    spam_alerts = carregar_spam_alerts()
                    if hour_key not in spam_alerts:
                        spam_alerts[hour_key] = {}
                    if citizenid not in spam_alerts[hour_key]:
                        spam_alerts[hour_key][citizenid] = {"count": 0, "last_log": ""}
                    spam_alerts[hour_key][citizenid]["count"] += LOG_COUNT_THRESHOLD
                    spam_alerts[hour_key][citizenid]["last_log"] = log_exibir
                    salvar_spam_alerts(spam_alerts)

                    count = spam_alerts[hour_key][citizenid]["count"]
                    for cid in ALERT_CHANNELS:
                        await enviar_alerta_spam_embed(cid, log_exibir, count, hora_atual)
                elif not pular_alerta_salario and not citizenid:
                    trecho_mod = substituir_rhis5udie_por_vip(trecho)
                    alert_message = (
                        f"@everyone ALERTA DE SPAM DETECTADO!\n\n"
                        f"{texto_completo.strip()}\n\n"
                        f"LOG SUSPEITO DETECTADO 🧑🏻‍🎄"
                    )
                    for cid in ALERT_CHANNELS:
                        await enviar_alerta(cid, alert_message, "Alerta Spam")
                elif pular_alerta_salario:
                    logger.info("Alerta spam ignorado - reason legítimo: %s", reason)

                if spam_key in log_history:
                    del log_history[spam_key]


if __name__ == "__main__":
    if not TOKEN:
        logger.error("TOKEN não encontrado! Configure a variável TOKEN no arquivo .env")
        exit(1)
    client.run(TOKEN)
