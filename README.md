# Bot Anti Trigger SCC

Bot Discord que monitora logs de AddMoney (QBX) e envia alertas automáticos para detectar spam, dump de salário e salário legítimo.

---

## Como funciona

O bot fica conectado a um canal de logs e analisa cada mensagem que contém AddMoney. Quando detecta padrões suspeitos ou específicos, envia alertas para canais configurados.

### Fluxo geral

1. **Monitora** o canal definido em `TARGET_CHANNEL_ID`
2. **Identifica** mensagens com AddMoney (embeds ou texto)
3. **Extrai** dados: citizenid, valor, tipo (bank/cash), reason, timestamp da log
4. **Armazena** em JSON para análise temporal
5. **Dispara alertas** quando encontra os padrões configurados

---

## Sistemas de alerta

### 1. Spam (3 logs em 60 segundos)

**O que detecta:** Mesma pessoa (citizenid + valor + tipo) recebendo o mesmo valor 3 ou mais vezes em 60 segundos.

**Lógica:**
- Usa o **horário da log** (ex: `07:46:48 03-18-2026`), não o horário de recebimento
- Agrupa por `citizenid_valor_tipo` (ex: `MGI6236V_633_bank`)
- Conta quantas logs caem em uma janela de 60 segundos
- Persiste em `spam_logs.json` para manter histórico após reinício

**Alerta:** Embed laranja com "🚨 SPAM DETECTADO — Xx" e footer "Alertado Xx na hora 7" (hora da log).

**Canal:** `ALERT_CHANNELS`

---

### 2. Spam de salário legítimo (VIP/Comprado)

**O que detecta:** Mesmo padrão de spam, mas com reason legítimo: `Salario VIP`, `Salario Comprado` ou `Juli V`.

**Lógica:** Igual ao spam comum, mas envia para canal separado.

**Alerta:** Embed verde com "SPAM DE SALARIO - Xx".

**Canal:** `SALARY_LEGIT_ALERT_CHANNELS`

---

### 3. Dump de salário (~30 min)

**O que detecta:** Mesma pessoa recebendo valores 3000, 5000, 7000 ou 9000 **sem** reason legítimo, em intervalos de ~25–35 minutos.

**Lógica:**
- Armazena logs em `salary_logs.json`
- Procura cadeias de 2+ logs com intervalo entre 25 e 35 min
- Ignora se o reason for VIP/Comprado/Juli V

**Alerta:** Embed vermelho com "⚠️ SALÁRIO SEM REASON — ~30 MIN".

**Canal:** `SALARY_DUMP_ALERT_CHANNELS`

---

### 4. Salário legítimo (~30 min)

**O que detecta:** Mesma pessoa recebendo 3000/5000/7000/9000 **com** reason legítimo, em intervalos de ~25–35 min.

**Lógica:** Igual ao dump, mas só considera logs com reason VIP/Comprado/Juli V.

**Alerta:** Embed verde com "✅ SALÁRIO LEGÍTIMO — ~30 MIN".

**Canal:** `SALARY_LEGIT_ALERT_CHANNELS`

---

## Arquivos de dados

| Arquivo | Função |
|---------|--------|
| `spam_logs.json` | Logs recentes para detecção de spam (retenção 2h) |
| `spam_alerts.json` | Contagem de alertas por hora (limpeza após 24h sem uso) |
| `salary_logs.json` | Logs de salário suspeito para dump |
| `salary_legit_logs.json` | Logs de salário legítimo |

---

## Configuração (.env)

```env
TOKEN=                    # Token do bot (obrigatório)
TARGET_CHANNEL_ID=        # Canal de logs que o bot monitora
ALERT_CHANNELS=           # Canais de spam (IDs separados por vírgula)
SALARY_DUMP_ALERT_CHANNELS=   # Canal de dump de salário
SALARY_LEGIT_ALERT_CHANNELS=  # Canal de salário legítimo
TIME_WINDOW_SECONDS=60    # Janela para spam (padrão: 60)
LOG_COUNT_THRESHOLD=3     # Mínimo de logs para spam (padrão: 3)
```

---

## Instalação e execução

```bash
# Clonar / entrar no projeto
cd scc-antitrigger

# Criar ambiente virtual
python3 -m venv venv
source venv/bin/activate   # Linux/Mac
# ou: venv\Scripts\activate   # Windows

# Instalar dependências
pip install -r requirements.txt

# Configurar
cp .env.example .env
# Editar .env com TOKEN e canais

# Rodar
python bot.py
```

### Com PM2 (VPS)

```bash
cd ~/Desktop/scc-antitrigger
git pull
source venv/bin/activate
pip install -r requirements.txt
pm2 restart scc-antitrigger
```

---

## Dependências

- `discord.py` — API do Discord
- `python-dotenv` — Variáveis de ambiente
