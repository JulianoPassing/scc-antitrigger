module.exports = {
  apps: [
    {
      name: 'scc-antitrigger',
      script: 'bot.py',
      interpreter: '/usr/bin/python3.11',
      cwd: '/home/juliano/Desktop/scc-antitrigger',
      env: {
        NODE_ENV: 'production'
      },
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      log_file: './logs/combined.log',
      out_file: './logs/out.log',
      error_file: './logs/error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      instances: 1,
      exec_mode: 'fork'
    }
  ]
} 