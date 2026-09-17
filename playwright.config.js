const { defineConfig } = require("@playwright/test");

const port = process.env.TEST_PORT || 8002;

module.exports = defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `PYTHONPATH=./src .venv/bin/uvicorn options_app.api:create_app --factory --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/api/v1/health`,
    reuseExistingServer: !process.env.CI && !process.env.TEST_PORT,
    timeout: 120_000,
  },
});
