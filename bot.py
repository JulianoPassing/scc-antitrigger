import discord
import os
from dotenv import load_dotenv
import datetime
import re

load_dotenv()
TOKEN = os.getenv('TOKEN')
TARGET_CHANNEL_ID = 1315448683348758529

# Lista de canais para enviar alertas (ID do canal)
ALERT_CHANNELS = [
    1315448683348758529,  # Canal original
    1387430519582494883,  # Canal adicional
    # Adicione mais IDs de canais aqui
]

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)

# --- MEMÓRIA DO BOT ---
log_history = {}
alerted_logs = {}  # Novo: rastrear logs que já dispararam alerta
# --- PARÂMETROS ATUALIZADOS ---
TIME_WINDOW_SECONDS = 60  # Janela de tempo em segundos (alterado para 60)
LOG_COUNT_THRESHOLD = 3   # Número de logs para disparar o alerta (alterado para 3)

def extrair_trecho(texto):
    match = re.search(r'(\*\*.*?added)', texto)
    if match:
        return match.group(1)
    return None

@client.event
async def on_ready():
    print(f'🤖 Bot Anti Trigger SCC conectado como {client.user}')
    print(f'📊 MODO AVANÇADO: Detectando {LOG_COUNT_THRESHOLD} logs idênticos em {TIME_WINDOW_SECONDS} segundos')
    print(f'🎯 Canal monitorado: {TARGET_CHANNEL_ID}')
    print(f'📢 Alertas enviados para: Canal {TARGET_CHANNEL_ID}')
    print(f'⏰ Janela de tempo: {TIME_WINDOW_SECONDS}s | Limite: {LOG_COUNT_THRESHOLD} logs')
    print(f'🛡️ Sistema anti-duplicação ativado')
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
            alert_message = (
                f"@everyone ALERTA DE SPAM DETECTADO!\n"
                f"{log_key}\n"
                f"LOG SUSPEITO DETECTADO 🧑🏻‍🎄"
            )
            
            # Enviar alerta apenas para o canal principal para evitar duplicatas
            try:
                target_channel = client.get_channel(TARGET_CHANNEL_ID)
                if target_channel:
                    await target_channel.send(alert_message)
                    print(f"✅ Alerta enviado para canal: {TARGET_CHANNEL_ID}")
                else:
                    print(f"❌ Canal não encontrado: {TARGET_CHANNEL_ID}")
            except Exception as e:
                print(f"❌ ERRO ao enviar alerta: {e}")

            # Limpar histórico deste log após enviar alerta
            if log_key in log_history:
                del log_history[log_key]

if TOKEN:
    client.run(TOKEN)
