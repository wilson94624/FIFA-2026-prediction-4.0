import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { exec } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    {
      name: 'sync-backend-plugin',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url === '/api/sync') {
            const projectRoot = path.resolve(__dirname, '..');
            exec(
              '/opt/anaconda3/bin/python3 backend/sync_real_games.py',
              { cwd: projectRoot },
              (error, stdout, stderr) => {
                res.setHeader('Content-Type', 'application/json');
                if (error) {
                  console.error(`Sync error: ${error.message}`);
                  res.statusCode = 500;
                  res.end(JSON.stringify({ success: false, error: error.message }));
                  return;
                }
                console.log(`Sync complete: ${stdout}`);
                res.end(JSON.stringify({ success: true }));
              }
            );
          } else if (req.url === '/api/sync-llm') {
            const projectRoot = path.resolve(__dirname, '..');
            exec(
              '/opt/anaconda3/bin/python3 backend/player_level_simulator.py',
              { cwd: projectRoot },
              (error, stdout, stderr) => {
                res.setHeader('Content-Type', 'application/json');
                if (error) {
                  console.error(`LLM Sync error: ${error.message}`);
                  res.statusCode = 500;
                  res.end(JSON.stringify({ success: false, error: error.message }));
                  return;
                }
                console.log(`LLM Sync and simulation complete: ${stdout}`);
                res.end(JSON.stringify({ success: true }));
              }
            );
          } else {
            next();
          }
        });
      }
    }
  ],
  server: {
    allowedHosts: true
  }
})
