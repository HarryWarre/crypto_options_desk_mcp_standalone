const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:8002",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "PYTHONPATH=./src .venv/bin/uvicorn options_app.api:create_app --factory --host 127.0.0.1 --port 8002",
    url: "http://127.0.0.1:8002/api/v1/health",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
