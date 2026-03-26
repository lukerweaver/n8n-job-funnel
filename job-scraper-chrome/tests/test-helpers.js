import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

import { JSDOM } from 'jsdom';

const __dirname = dirname(fileURLToPath(import.meta.url));

export function readScript(name) {
  return readFileSync(resolve(__dirname, '..', name), 'utf8').replace(/^\uFEFF/, '');
}

export function createDom({ html = '<!doctype html><html><body></body></html>', url = 'https://example.com/', beforeParse } = {}) {
  return new JSDOM(html, {
    url,
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    beforeParse(window) {
      if (beforeParse) beforeParse(window);
    }
  });
}

export function evalScript(dom, name) {
  dom.window.eval(readScript(name));
}

export function runScriptInContext(name, context) {
  vm.runInNewContext(readScript(name), context);
  return context;
}

export async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await Promise.resolve();
}
