import discord
import os
import json
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

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)

# --- MEMÓRIA DO BOT ---
log_history = {}
alerted_logs = {}  # Rastrear logs que já dispararam alerta de spam
alerted_salary_dump = {}  # Rastrear logs que já dispararam alerta de dump de salário
alerted_salary_interval = {}  # Rastrear cidadãos que já dispararam alerta de intervalo 30 min
# --- PARÂMETROS ATUALIZADOS ---
TIME_WINDOW_SECONDS = 180  # Janela de tempo em segundos (alterado para 60)
LOG_COUNT_THRESHOLD = 3   # Número de logs para disparar o alerta (alterado para 3)
SALARY_DUMP_VALUES = {3000, 5000, 7000, 9000}  # Valores suspeitos de dump de salário
SALARY_LOG_FILE = Path(__file__).parent / "salary_logs.json"
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

def verificar_intervalo_30min(entries):
    """
    Verifica se há 2+ entradas com intervalo ~30 min entre elas.
    entries: lista de {"timestamp": "ISO", "value": N, "reason": "..."}
    """
    if len(entries) < 2:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(seconds=SALARY_LOG_RETENTION)
    valid = []
    for e in entries:
        try:
            ts = datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
            if ts > cutoff:
                valid.append(ts)
        except (ValueError, KeyError):
            continue
    valid.sort()
    for i in range(len(valid) - 1):
        delta = (valid[i + 1] - valid[i]).total_seconds()
        if SALARY_INTERVAL_MIN <= delta <= SALARY_INTERVAL_MAX:
            return True
    return False

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

@client.event
async def on_ready():
    print(f'🤖 Bot Anti Trigger SCC conectado como {client.user}')
    print(f'📊 MODO AVANÇADO: Detectando {LOG_COUNT_THRESHOLD} logs idênticos em {TIME_WINDOW_SECONDS} segundos')
    print(f'🎯 Canal monitorado: {TARGET_CHANNEL_ID} (Servidor 1313305951004135434)')
    print(f'📢 Alertas enviados para: {len(ALERT_CHANNELS)} canais')
    print(f'   📢 Canal 1387430519582494883 (Servidor 1313305951004135434)')
    print(f'   📢 Canal 1421954201969496158 (Servidor 1046404063287332936)')
    print(f'⏰ Janela de tempo: {TIME_WINDOW_SECONDS}s | Limite: {LOG_COUNT_THRESHOLD} logs')
    print(f'🛡️ Sistema anti-duplicação ativado')
    print(f'💰 Alerta Dump Salário: valores {SALARY_DUMP_VALUES} em (bank) - reason diferente de Salario Comprado/Salario VIP')
    print(f'📅 Detecção intervalo 30 min: salário sem reason a cada ~30 min (armazenado em {SALARY_LOG_FILE.name})')
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
                # Verificar padrão de 30 em 30 min
                if verificar_intervalo_30min(logs[citizenid]):
                    for key in list(alerted_salary_interval.keys()):
                        if (now - alerted_salary_interval[key]).total_seconds() >= TIME_WINDOW_SECONDS:
                            del alerted_salary_interval[key]
                    if citizenid not in alerted_salary_interval:
                        alerted_salary_interval[citizenid] = now
                        trecho_mod = substituir_rhis5udie_por_vip(trecho)
                        alert_interval = (
                            f"@everyone ⚠️ SALÁRIO SEM REASON EM INTERVALOS DE ~30 MIN!\n"
                            f"{trecho_mod}\n"
                            f"CitizenID: {citizenid} - Valores de salário caindo a cada ~30 min sem reason correto"
                        )
                        for alert_channel_id in SALARY_DUMP_ALERT_CHANNELS:
                            try:
                                target_channel = client.get_channel(alert_channel_id)
                                if target_channel:
                                    await target_channel.send(alert_interval)
                                    print(f"✅ Alerta Intervalo 30min enviado para canal: {alert_channel_id}")
                                else:
                                    print(f"❌ Canal não encontrado: {alert_channel_id}")
                            except Exception as e:
                                print(f"❌ ERRO ao enviar alerta intervalo para canal {alert_channel_id}: {e}")
                        # Limpar histórico deste cidadão após alertar
                        if citizenid in logs:
                            del logs[citizenid]
                            salvar_salary_logs(logs)

            # Alerta de dump único (reason incorreto)
            for key in list(alerted_salary_dump.keys()):
                if (now - alerted_salary_dump[key]).total_seconds() >= TIME_WINDOW_SECONDS:
                    del alerted_salary_dump[key]
            if log_key not in alerted_salary_dump:
                alerted_salary_dump[log_key] = now
                trecho_mod = substituir_rhis5udie_por_vip(trecho)
                alert_dump = (
                    f"@everyone ⚠️ POSSÍVEL DUMP DE SALÁRIO!\n"
                    f"{trecho_mod}\n"
                    f"Valor: ${valor} (bank) - reason: \"{reason}\" (esperado: Salario Comprado ou Salario VIP)"
                )
                for alert_channel_id in SALARY_DUMP_ALERT_CHANNELS:
                    try:
                        target_channel = client.get_channel(alert_channel_id)
                        if target_channel:
                            await target_channel.send(alert_dump)
                            print(f"✅ Alerta Dump Salário enviado para canal: {alert_channel_id}")
                        else:
                            print(f"❌ Canal não encontrado: {alert_channel_id}")
                    except Exception as e:
                        print(f"❌ ERRO ao enviar alerta dump para canal {alert_channel_id}: {e}")

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

        log_count = len(log_history[log_key])

        print(f"Log de AddMoney detectado. Chave: '{log_key[:30]}...'. Contagem atual: {log_count}/{LOG_COUNT_THRESHOLD}")

        if log_count == LOG_COUNT_THRESHOLD:
            print(f"!!! ALERTA DE SPAM DISPARADO !!! Chave: {log_key}")
            
            # Marcar este log como já alertado
            alerted_logs[log_key] = now
            
            # Nova mensagem de alerta
            log_key_modificado = substituir_rhis5udie_por_vip(log_key)
            alert_message = (
                f"@everyone ALERTA DE SPAM DETECTADO!\n"
                f"{log_key_modificado}\n"
                f"LOG SUSPEITO DETECTADO 🧑🏻‍🎄"
            )
            
            # Enviar alerta para todos os canais configurados
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

            # Limpar histórico deste log após enviar alerta
            if log_key in log_history:
                del log_history[log_key]

if TOKEN:
    client.run(TOKEN)