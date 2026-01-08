module.exports = {
  apps: [{
    name: 'scc-antitrigger',
    script: 'bot.py',
    interpreter: 'python3',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    env: {
      NODE_ENV: 'production'
    }
  }]
};
