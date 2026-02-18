import discord
import os
import json
import hashlib
from pathlib import Path
from dotenv import load_dotenv
import datetime
import re

load_dotenv()
TOKEN = os.getenv('TOKEN')
TARGET_CHANNEL_ID = 1398496668537716896  # Canal do servidor 1313305951004135434

# Lista de canais para enviar alertas de spam (ID do canal)
ALERT_CHANNELS = [
    1387430519582494883,  # Canal do servidor 1313305951004135434
    1421954201969496158,  # Canal do servidor 1046404063287332936
    # Adicione mais IDs de canais aqui
]

# Canal para alertas de dump de salário (Servidor 1046404063287332936)
SALARY_DUMP_ALERT_CHANNELS = [
    1471831384837460136,  # Canal do servidor 1046404063287332936
]

# Canal para alertas de salário legítimo (reason Salario Comprado/VIP) - Servidor 1046404063287332936
SALARY_LEGIT_ALERT_CHANNELS = [
    1473755075670310942,  # Canal do servidor 1046404063287332936
]

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)

# --- MEMÓRIA DO BOT ---
log_history = {}
alerted_logs = {}  # Rastrear logs que já dispararam alerta de spam
alerted_salary_chains = {}  # citizenid -> (tuple de timestamps) da cadeia já alertada (dump)
alerted_salary_legit_chains = {}  # citizenid -> (tuple de timestamps) da cadeia já alertada (legítimo)
# --- PARÂMETROS ATUALIZADOS ---
TIME_WINDOW_SECONDS = 60  # Janela de tempo para spam: 3 logs a cada 60 segundos
LOG_COUNT_THRESHOLD = 3   # Número de logs para disparar o alerta de spam
SALARY_DUMP_VALUES = {3000, 5000, 7000, 9000}  # Valores suspeitos de dump de salário
SALARY_LOG_FILE = Path(__file__).parent / "salary_logs.json"
SALARY_LEGIT_LOG_FILE = Path(__file__).parent / "salary_legit_logs.json"
SPAM_LOG_FILE = Path(__file__).parent / "spam_logs.json"
SPAM_LOG_RETENTION = 2 * 60 * 60  # Manter logs de spam por 2 horas
SALARY_INTERVAL_MIN = 25 * 60  # 25 min em segundos
SALARY_INTERVAL_MAX = 35 * 60  # 35 min em segundos (média 30 min)
SALARY_LOG_RETENTION = 2 * 60 * 60  # Manter logs por 2 horas

def extrair_trecho(texto):
    match = re.search(r'(\*\*.*?added)', texto)
    if match:
        return match.group(1)
    return None

def substituir_rhis5udie_por_vip(texto):
    """Substitui 'rhis5udie' por 'vip' na mensagem de alerta"""
    # Substitui rhis5udie por vip (mantendo sufixos como _dlc)
    texto = re.sub(r'rhis5udie(_dlc)?', r'vip\1', texto)
    return texto

REASONS_SALARIO_LEGITIMOS = ("salario comprado", "salario vip")

def extrair_citizenid(texto):
    """Extrai o citizenid do log. Ex: citizenid: ORF6AWXX"""
    match = re.search(r'citizenid:\s*([A-Z0-9]+)', texto, re.IGNORECASE)
    return match.group(1) if match else None

def carregar_salary_logs():
    """Carrega logs de salário do JSON"""
    try:
        if SALARY_LOG_FILE.exists():
            with open(SALARY_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {}

def salvar_salary_logs(data):
    """Salva logs de salário no JSON"""
    try:
        with open(SALARY_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"❌ Erro ao salvar salary_logs.json: {e}")

def carregar_salary_legit_logs():
    """Carrega logs de salário legítimo do JSON"""
    try:
        if SALARY_LEGIT_LOG_FILE.exists():
            with open(SALARY_LEGIT_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {}

def salvar_salary_legit_logs(data):
    """Salva logs de salário legítimo no JSON"""
    try:
        with open(SALARY_LEGIT_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"❌ Erro ao salvar salary_legit_logs.json: {e}")

def spam_log_key_hash(log_key):
    """Gera hash para usar como chave no JSON de spam"""
    return hashlib.md5(log_key.encode("utf-8")).hexdigest()[:24]

def carregar_spam_logs():
    """Carrega logs de spam do JSON"""
    try:
        if SPAM_LOG_FILE.exists():
            with open(SPAM_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {}

def salvar_spam_logs(data):
    """Salva logs de spam no JSON"""
    try:
        with open(SPAM_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"❌ Erro ao salvar spam_logs.json: {e}")

def encontrar_cadeia_30min(entries):
    """
    Encontra a maior cadeia de entradas com intervalo ~30 min entre consecutivas.
    entries: lista de {"timestamp": "ISO", "value": N, "reason": "..."}
    Retorna: lista de entradas da cadeia (2, 3, 4 ou mais) ou [] se não houver
    """
    if len(entries) < 2:
        return []
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(seconds=SALARY_LOG_RETENTION)
    valid = []
    for e in entries:
        try:
            ts = datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
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
    """
    Verifica se o log indica possível dump de salário.
    Condições: valor 3000/5000/7000/9000 + (bank) + reason diferente de Salario Comprado/Salario VIP
    Retorna: (é_dump, valor, reason_extraido)
    """
    if "(bank)" not in texto.lower():
        return False, None, None
    # Extrair o reason e verificar se é legítimo
    match_reason = re.search(r'reason:\s*([^\n*]+)', texto, re.IGNORECASE)
    reason_extraido = match_reason.group(1).strip() if match_reason else "não encontrado"
    if match_reason:
        reason_lower = reason_extraido.lower()
        if reason_lower in REASONS_SALARIO_LEGITIMOS:
            return False, None, None
    match = re.search(r'\$(\d+)', texto)
    if not match:
        return False, None, None
    valor = int(match.group(1))
    if valor not in SALARY_DUMP_VALUES:
        return False, None, None
    return True, valor, reason_extraido

def verificar_salario_legitimo(texto, trecho):
    """
    Verifica se o log é salário legítimo (Salario Comprado ou Salario VIP).
    Condições: valor 3000/5000/7000/9000 + (bank) + reason Salario Comprado ou Salario VIP
    Retorna: (é_legit, valor, reason_extraido)
    """
    if "(bank)" not in texto.lower():
        return False, None, None
    match_reason = re.search(r'reason:\s*([^\n*]+)', texto, re.IGNORECASE)
    reason_extraido = match_reason.group(1).strip() if match_reason else ""
    if not match_reason:
        return False, None, None
    reason_lower = reason_extraido.lower()
    if reason_lower not in REASONS_SALARIO_LEGITIMOS:
        return False, None, None
    match = re.search(r'\$(\d+)', texto)
    if not match:
        return False, None, None
    valor = int(match.group(1))
    if valor not in SALARY_DUMP_VALUES:
        return False, None, None
    return True, valor, reason_extraido

@client.event
async def on_ready():
    print(f'🤖 Bot Anti Trigger SCC conectado como {client.user}')
    print(f'📊 MODO AVANÇADO: Detectando {LOG_COUNT_THRESHOLD} logs idênticos em {TIME_WINDOW_SECONDS} segundos')
    print(f'🎯 Canal monitorado: {TARGET_CHANNEL_ID} (Servidor 1313305951004135434)')
    print(f'📢 Alertas enviados para: {len(ALERT_CHANNELS)} canais')
    print(f'   📢 Canal 1387430519582494883 (Servidor 1313305951004135434)')
    print(f'   📢 Canal 1421954201969496158 (Servidor 1046404063287332936)')
    print(f'⏰ Spam: {LOG_COUNT_THRESHOLD} logs em {TIME_WINDOW_SECONDS}s')
    print(f'🛡️ Sistema anti-duplicação ativado')
    print(f'📁 Spam: logs acumulados em {SPAM_LOG_FILE.name}')
    print(f'💰 Alerta Dump Salário: canal 1471831384837460136 (2+ logs, reason incorreto)')
    print(f'✅ Alerta Salário Legítimo: canal 1473755075670310942 (2+ logs, Salario Comprado/VIP)')
    print(f'✅ Bot online e monitorando...')

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

    if "addmoney" in texto_lower and "citizenid" in texto_lower and "id" in texto_lower and "added" in texto_lower:
        now = datetime.datetime.now()

        trecho = extrair_trecho(texto_completo)
        if not trecho:
            return  # Não encontrou o padrão desejado
        log_key = trecho

        # --- ALERTA: Possível Dump de Salário ---
        # Valores 3000/5000/7000/9000 em (bank) com reason incorreto
        é_dump, valor, reason = verificar_dump_salario(texto_completo, trecho)
        if é_dump:
            # Registrar no JSON para detecção de intervalo 30 em 30 min
            citizenid = extrair_citizenid(texto_completo)
            if citizenid:
                logs = carregar_salary_logs()
                if citizenid not in logs:
                    logs[citizenid] = []
                logs[citizenid].append({
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "value": valor,
                    "reason": reason,
                })
                # Limpar entradas antigas (mais de 2h)
                cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=SALARY_LOG_RETENTION)
                logs[citizenid] = [
                    e for e in logs[citizenid]
                    if datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")) > cutoff
                ]
                salvar_salary_logs(logs)
                # Verificar padrão de 30 em 30 min (cadeia de 2, 3, 4 ou mais)
                cadeia_logs = encontrar_cadeia_30min(logs[citizenid])
                if cadeia_logs:
                    # Evitar alerta duplicado: só alertar se a cadeia for nova (mais logs que a última alertada)
                    chain_key = tuple(e["timestamp"] for e in cadeia_logs)
                    ultima_cadeia = alerted_salary_chains.get(citizenid)
                    if ultima_cadeia and chain_key == ultima_cadeia:
                        pass  # Mesma cadeia já alertada, não enviar de novo
                    else:
                        alerted_salary_chains[citizenid] = chain_key
                        trecho_mod = substituir_rhis5udie_por_vip(trecho)
                        def fmt_log(i, e):
                            ts = datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
                            horario = ts.strftime("%d-%m-%Y %H:%M:%S")
                            return f"  {i}. ${e['value']} (bank) - reason: {e['reason']} | {horario}"
                        logs_texto = "\n".join(fmt_log(i + 1, e) for i, e in enumerate(cadeia_logs))
                        alert_interval = (
                            f"@everyone ⚠️ SALÁRIO SEM REASON EM INTERVALOS DE ~30 MIN!\n"
                            f"{trecho_mod}\n"
                            f"CitizenID: {citizenid} - {len(cadeia_logs)} logs em ~30 min sem reason correto\n\n"
                            f"**Logs detectados no intervalo:**\n{logs_texto}"
                        )
                        for alert_channel_id in SALARY_DUMP_ALERT_CHANNELS:
                            try:
                                target_channel = client.get_channel(alert_channel_id)
                                if target_channel:
                                    await target_channel.send(alert_interval)
                                    print(f"✅ Alerta Intervalo 30min ({len(cadeia_logs)} logs) enviado para canal: {alert_channel_id}")
                                else:
                                    print(f"❌ Canal não encontrado: {alert_channel_id}")
                            except Exception as e:
                                print(f"❌ ERRO ao enviar alerta intervalo para canal {alert_channel_id}: {e}")

        # --- ALERTA: Salário Legítimo (Salario Comprado / Salario VIP) ---
        é_legit, valor_legit, reason_legit = verificar_salario_legitimo(texto_completo, trecho)
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
                })
                cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=SALARY_LOG_RETENTION)
                logs[citizenid] = [
                    e for e in logs[citizenid]
                    if datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")) > cutoff
                ]
                salvar_salary_legit_logs(logs)
                cadeia_logs = encontrar_cadeia_30min(logs[citizenid])
                if cadeia_logs:
                    chain_key = tuple(e["timestamp"] for e in cadeia_logs)
                    ultima_cadeia = alerted_salary_legit_chains.get(citizenid)
                    if ultima_cadeia and chain_key == ultima_cadeia:
                        pass
                    else:
                        alerted_salary_legit_chains[citizenid] = chain_key
                        trecho_mod = substituir_rhis5udie_por_vip(trecho)
                        def fmt_log_legit(i, e):
                            ts = datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
                            horario = ts.strftime("%d-%m-%Y %H:%M:%S")
                            return f"  {i}. ${e['value']} (bank) - reason: {e['reason']} | {horario}"
                        logs_texto = "\n".join(fmt_log_legit(i + 1, e) for i, e in enumerate(cadeia_logs))
                        alert_legit = (
                            f"@everyone ✅ SALÁRIO LEGÍTIMO EM INTERVALOS DE ~30 MIN\n"
                            f"{trecho_mod}\n"
                            f"CitizenID: {citizenid} - {len(cadeia_logs)} logs em ~30 min (reason correto)\n\n"
                            f"**Logs detectados:**\n{logs_texto}"
                        )
                        for alert_channel_id in SALARY_LEGIT_ALERT_CHANNELS:
                            try:
                                target_channel = client.get_channel(alert_channel_id)
                                if target_channel:
                                    await target_channel.send(alert_legit)
                                    print(f"✅ Alerta Salário Legítimo ({len(cadeia_logs)} logs) enviado para canal: {alert_channel_id}")
                                else:
                                    print(f"❌ Canal não encontrado: {alert_channel_id}")
                            except Exception as e:
                                print(f"❌ ERRO ao enviar alerta salário legítimo para canal {alert_channel_id}: {e}")

        # Limpeza do histórico antigo
        for key in list(log_history.keys()):
            timestamps = log_history[key]
            valid_timestamps = [ts for ts in timestamps if (now - ts).total_seconds() < TIME_WINDOW_SECONDS]
            if not valid_timestamps:
                del log_history[key]
            else:
                log_history[key] = valid_timestamps

        # Limpeza dos logs já alertados (usar mesma janela de tempo)
        for key in list(alerted_logs.keys()):
            if (now - alerted_logs[key]).total_seconds() >= TIME_WINDOW_SECONDS:
                del alerted_logs[key]

        # Verificar se este log já disparou alerta recentemente
        if log_key in alerted_logs:
            return  # Evita aviso duplicado

        if log_key not in log_history:
            log_history[log_key] = []
        log_history[log_key].append(now)

        # Acumular no JSON para histórico de spam
        spam_data = carregar_spam_logs()
        key_hash = spam_log_key_hash(log_key)
        if key_hash not in spam_data:
            spam_data[key_hash] = {"trecho": log_key, "logs": []}
        spam_data[key_hash]["logs"].append({
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        spam_data[key_hash]["trecho"] = log_key
        # Limpar entradas antigas ao acumular
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=SPAM_LOG_RETENTION)
        spam_data[key_hash]["logs"] = [
            e for e in spam_data[key_hash]["logs"]
            if datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")) > cutoff
        ]
        salvar_spam_logs(spam_data)

        log_count = len(log_history[log_key])

        print(f"Log de AddMoney detectado. Chave: '{log_key[:30]}...'. Contagem atual: {log_count}/{LOG_COUNT_THRESHOLD}")

        if log_count == LOG_COUNT_THRESHOLD:
            print(f"!!! ALERTA DE SPAM DISPARADO !!! Chave: {log_key}")
            
            # Marcar este log como já alertado
            alerted_logs[log_key] = now
            
            # Não enviar alerta se o reason for Salario Comprado ou Salario VIP
            match_reason = re.search(r'reason:\s*([^\n*]+)', texto_completo, re.IGNORECASE)
            reason = match_reason.group(1).strip().lower() if match_reason else ""
            pular_alerta_salario = reason in REASONS_SALARIO_LEGITIMOS
            
            if not pular_alerta_salario:
                log_key_modificado = substituir_rhis5udie_por_vip(log_key)
                # Carregar logs acumulados do JSON e mesclar com atuais
                spam_data = carregar_spam_logs()
                key_hash = spam_log_key_hash(log_key)
                if key_hash in spam_data:
                    all_logs = spam_data[key_hash]["logs"]
                else:
                    all_logs = []
                # Limpar entradas antigas (mais de 2h)
                cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=SPAM_LOG_RETENTION)
                all_logs = [
                    e for e in all_logs
                    if datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")) > cutoff
                ]
                # Ordenar por timestamp
                all_logs.sort(key=lambda e: e["timestamp"])
                # Atualizar JSON com logs limpos
                spam_data[key_hash] = {"trecho": log_key, "logs": all_logs}
                salvar_spam_logs(spam_data)
                logs_texto = "\n".join(
                    f"  {i + 1}. {datetime.datetime.fromisoformat(e['timestamp'].replace('Z', '+00:00')).strftime('%d-%m-%Y %H:%M:%S')}"
                    for i, e in enumerate(all_logs)
                )
                alert_message = (
                    f"@everyone ALERTA DE SPAM DETECTADO!\n"
                    f"{log_key_modificado}\n"
                    f"LOG SUSPEITO DETECTADO 🧑🏻‍🎄\n\n"
                    f"**Logs acumulados ({len(all_logs)} total, janela {SPAM_LOG_RETENTION//3600}h):**\n{logs_texto}"
                )
                for alert_channel_id in ALERT_CHANNELS:
                    try:
                        target_channel = client.get_channel(alert_channel_id)
                        if target_channel:
                            await target_channel.send(alert_message)
                            print(f"✅ Alerta enviado para canal: {alert_channel_id}")
                        else:
                            print(f"❌ Canal não encontrado: {alert_channel_id}")
                    except Exception as e:
                        print(f"❌ ERRO ao enviar alerta para canal {alert_channel_id}: {e}")
            else:
                print(f"⏭️ Alerta de spam ignorado - reason legítimo: {reason}")

            # Limpar histórico deste log após processar
            if log_key in log_history:
                del log_history[log_key]

if TOKEN:
    client.run(TOKEN)