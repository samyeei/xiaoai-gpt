import { existsSync, mkdirSync, writeFileSync, readFileSync, statSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

export const projectRoot=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
export const defaultConfig=resolve(projectRoot,'mac/codex-service/private/config.json');
export function validateConfig(config) {
  if(config.model!==undefined&&(typeof config.model!=='string'|| !/^[a-zA-Z0-9._-]{1,100}$/.test(config.model)))throw new Error('Invalid model selection');
  if(config.cwd!==projectRoot || typeof config.executable!=='string' || !config.executable.startsWith('/') ||
    !/^(127\.0\.0\.1|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})$/.test(config.host) ||
    !['port','control_port'].every(p=>Number.isInteger(config[p])&&config[p]>=1024&&config[p]<=65535) || config.port===config.control_port ||
    !/^[a-f0-9]{64}$/.test(config.key) || !/^[a-f0-9]{64}$/.test(config.admin_key) || config.key===config.admin_key)throw new Error('Invalid local service configuration');
  return config;
}
export function loadConfig(path=defaultConfig) {
  if((statSync(path).mode & 0o077)!==0)throw new Error('Config must be private (chmod 600)');
  return validateConfig(JSON.parse(readFileSync(path,'utf8')));
}
export function initializeConfig(host='127.0.0.1',path=defaultConfig) {
  if(existsSync(path))throw new Error('Config already exists; refusing to replace keys');
  const config=validateConfig({cwd:projectRoot,executable:process.env.CODEX_BIN ?? execFileSync('/usr/bin/which',['codex'],{encoding:'utf8'}).trim(),
    host,port:4411,control_port:4412,key:randomBytes(32).toString('hex'),admin_key:randomBytes(32).toString('hex')});
  mkdirSync(dirname(path),{recursive:true,mode:0o700});writeFileSync(path,JSON.stringify(config,null,2)+'\n',{mode:0o600,flag:'wx'});return path;
}
