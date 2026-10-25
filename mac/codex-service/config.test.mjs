import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,chmodSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {initializeConfig,loadConfig,validateConfig} from './config.mjs';
test('local config uses distinct keys, refuses replacement and rejects public permissions or arbitrary cwd',t=>{
  // Config validation does not execute Codex; keep this unit test independent
  // of a developer's installed CLI and PATH (including clean CI runners).
  const originalExecutable=process.env.CODEX_BIN;
  process.env.CODEX_BIN=process.execPath;
  t.after(()=>{if(originalExecutable===undefined)delete process.env.CODEX_BIN;else process.env.CODEX_BIN=originalExecutable;});
  const dir=mkdtempSync(join(tmpdir(),'codex-config-'));t.after(()=>rmSync(dir,{recursive:true,force:true}));const path=join(dir,'config.json');
  initializeConfig('127.0.0.1',path);const cfg=loadConfig(path);assert.notEqual(cfg.key,cfg.admin_key);
  assert.throws(()=>initializeConfig('127.0.0.1',path),/already exists/);
  assert.throws(()=>validateConfig({...cfg,cwd:'/tmp'}),/Invalid/);
  assert.throws(()=>validateConfig({...cfg,host:'0.0.0.0'}),/Invalid/);
  chmodSync(path,0o644);assert.throws(()=>loadConfig(path),/private/);
});
