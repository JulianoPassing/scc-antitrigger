module.exports = {
  apps: [
    {
      name: 'scc-antitrigger-bot-1',
      script: 'bot.py',
      interpreter: './venv/bin/python',
      cwd: '/root/Desktop/scc-antitrigger',
      env: {
        NODE_ENV: 'production',
        INSTANCE: '1'
      },
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      log_file: './logs/combined.log',
      out_file: './logs/out-1.log',
      error_file: './logs/error-1.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    },
    {
      name: 'scc-antitrigger-bot-2',
      script: 'bot.py',
      interpreter: './venv/bin/python',
      cwd: '/root/Desktop/scc-antitrigger',
      env: {
        NODE_ENV: 'production',
        INSTANCE: '2'
      },
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      log_file: './logs/combined.log',
      out_file: './logs/out-2.log',
      error_file: './logs/error-2.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    }
  ]
} 