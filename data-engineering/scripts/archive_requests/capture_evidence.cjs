// Capture screenshots of the evidence page generated from actual local results.
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const root = path.resolve(__dirname, '..', '..', '..');
  const browser = await playwright.chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_EXECUTABLE ? {executablePath: process.env.PLAYWRIGHT_EXECUTABLE} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1450, height: 1100}, deviceScaleFactor: 1});
    await page.goto(pathToFileURL(path.join(root, 'data-engineering', 'docs', 'archive_requests', 'evidence', 'report.html')).href);
    await page.locator('#execution').screenshot({path: path.join(root, 'data-engineering', 'docs', 'archive_requests', 'evidence', 'local-execution.png')});
    await page.locator('#output').screenshot({path: path.join(root, 'data-engineering', 'docs', 'archive_requests', 'evidence', 'exported-output.png')});
    console.log('Saved local-execution.png and exported-output.png from the generated evidence page.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });


