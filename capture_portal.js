#!/usr/bin/env node
/* Captura el catálogo de precios del portal de Nous (portal.nousresearch.com)
 * y lo escribe en portal.md con el mismo formato markdown que web_extract:
 *   - [Label in $X / out $Y per 1M](https://openrouter.ai/slug)
 *
 * El portal bloquea curl (Vercel Security Checkpoint, HTTP 429) y es una SPA
 * Next.js: el listado de modelos solo aparece tras renderizar y hacer scroll.
 * Por eso se usa Playwright + Chromium (ya instalados en esta máquina).
 *
 * Uso:
 *   node capture_portal.js [ruta_salida]   # default: portal.md
 */
const { chromium } = require('/home/rafaelroa/workspace/RRSO/node_modules/playwright');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, 'portal.md');
const CHROME = '/home/rafaelroa/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome';
const URL = 'https://portal.nousresearch.com/';
const UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36';

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage({ userAgent: UA });
    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 90000 });
    // esperar a que pase el checkpoint y se hidrate la SPA
    await page.waitForTimeout(10000);
    // scroll hasta el final para forzar el lazy-load del listado de modelos
    await page.evaluate(async () => {
      for (let i = 0; i < 25; i++) {
        window.scrollBy(0, document.body.scrollHeight / 25);
        await new Promise((r) => setTimeout(r, 350));
      }
    });
    await page.waitForTimeout(3000);

    const links = await page.evaluate(() =>
      [...document.querySelectorAll('a[href*="openrouter.ai"]')]
        .map((a) => `[${a.textContent.trim()}](${a.href})`)
    );
    if (links.length < 100) {
      throw new Error(`Solo ${links.length} enlaces OpenRouter; la SPA no cargó el listado completo`);
    }
    const md = links.join('\n') + '\n';
    fs.writeFileSync(OUT, md, 'utf-8');
    console.log(`OK: ${links.length} modelos -> ${OUT}`);
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(`ERROR captura portal: ${e.message}`);
  process.exit(1);
});
