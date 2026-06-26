const { spawn } = require('child_process');
const http = require('http');
const path = require('path');

const server = spawn(process.execPath, ['static-server.js'], { stdio: 'pipe' });

// Use the actual Playwright CLI entry point, not the shell wrapper
const playwrightCli = path.join(__dirname, 'node_modules', '@playwright', 'test', 'cli.js');

function waitForServer(retries = 20) {
  http.get('http://127.0.0.1:8081/', (res) => {
    const args = ['test', ...process.argv.slice(2)];
    const playwright = spawn(process.execPath, [playwrightCli, ...args], {
      stdio: 'inherit',
    });
    playwright.on('exit', (code) => {
      server.kill();
      process.exit(code ?? 0);
    });
  }).on('error', () => {
    if (retries > 0) {
      setTimeout(() => waitForServer(retries - 1), 300);
    } else {
      console.error('Server did not start in time');
      server.kill();
      process.exit(1);
    }
  });
}

server.on('error', (err) => {
  console.error('Failed to start server:', err);
  process.exit(1);
});

setTimeout(() => waitForServer(), 500);
