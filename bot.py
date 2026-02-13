import discord
import os
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
# --- PARÂMETROS ATUALIZADOS ---
TIME_WINDOW_SECONDS = 180  # Janela de tempo em segundos (alterado para 60)
LOG_COUNT_THRESHOLD = 3   # Número de logs para disparar o alerta (alterado para 3)
SALARY_DUMP_VALUES = {3000, 5000, 7000, 9000}  # Valores suspeitos de dump de salário

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
        # Valores 3000/5000/7000/9000 em (bank) com reason: unknown
        é_dump, valor, reason = verificar_dump_salario(texto_completo, trecho)
        if é_dump:
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