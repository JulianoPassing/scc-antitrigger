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
# --- PARÂMETROS ATUALIZADOS ---
TIME_WINDOW_SECONDS = 120  # Janela de tempo em segundos
LOG_COUNT_THRESHOLD = 2   # Número de logs para disparar o alerta

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
    print(f'📢 Canais de alerta: {len(ALERT_CHANNELS)} canais configurados')
    print(f'⏰ Janela de tempo: {TIME_WINDOW_SECONDS}s | Limite: {LOG_COUNT_THRESHOLD} logs')
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

        for key in list(log_history.keys()):
            timestamps = log_history[key]
            valid_timestamps = [ts for ts in timestamps if (now - ts).total_seconds() < TIME_WINDOW_SECONDS]
            if not valid_timestamps:
                del log_history[key]
            else:
                log_history[key] = valid_timestamps

        if log_key not in log_history:
            log_history[log_key] = []
        log_history[log_key].append(now)

        log_count = len(log_history[log_key])

        print(f"Log de AddMoney detectado. Chave: '{log_key[:30]}...'. Contagem atual: {log_count}/{LOG_COUNT_THRESHOLD}")

        if log_count == LOG_COUNT_THRESHOLD:
            print(f"!!! ALERTA DE SPAM DISPARADO !!! Chave: {log_key}")
            alert_message = (
                f"@everyone **ALERTA DE SPAM DETECTADO!**\n"
                f"**{LOG_COUNT_THRESHOLD}** logs idênticos recebidos em menos de {TIME_WINDOW_SECONDS} segundos.\n"
                f"\n**Trecho identificado:**\n"
                f"```\n{log_key}\n```\n"
                f"**Mensagem completa capturada:**\n"
                f"```\n{texto_completo}\n```"
            )
            
            # Enviar alerta para todos os canais configurados
            for channel_id in ALERT_CHANNELS:
                try:
                    target_channel = client.get_channel(channel_id)
                    if target_channel:
                        await target_channel.send(alert_message)
                        print(f"✅ Alerta enviado para canal: {channel_id}")
                    else:
                        print(f"❌ Canal não encontrado: {channel_id}")
                except Exception as e:
                    print(f"❌ ERRO ao enviar para canal {channel_id}: {e}")

            del log_history[log_key]

if TOKEN:
    client.run(TOKEN)
