import {mkdirSync,writeFileSync,existsSync} from 'node:fs';
import {homedir} from 'node:os';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
export function featureConfig(p){if(!p||typeof p.enabled!=='boolean'||Object.keys(p).some(k=>!['enabled','idle_seconds','max_session_seconds'].includes(k)))throw Error('Invalid realtime config');const idle=p.idle_seconds??60,max=p.max_session_seconds??900;if(!Number.isInteger(idle)||idle<10||idle>600||!Number.isInteger(max)||max<60||max>900)throw Error('Invalid session limits');return {enabled:p.enabled,idle_seconds:idle,max_session_seconds:max};}
const xml=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
export function launchAgent(root,logs){return `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict><key>Label</key><string>com.LOCAL_USER.xiaoai-realtime-voice</string><key>ProgramArguments</key><array><string>${xml(resolve(homedir(),'Applications/Xiaoai Native Voice.app/Contents/MacOS/node'))}</string><string>${xml(root)}/mac/realtime-voice/service.mjs</string></array><key>WorkingDirectory</key><string>${xml(root)}</string><key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>10</integer><key>ExitTimeOut</key><integer>30</integer><key>Umask</key><integer>63</integer><key>StandardOutPath</key><string>${xml(logs)}/stdout.log</string><key>StandardErrorPath</key><string>${xml(logs)}/stderr.log</string></dict></plist>\n`;}
if(process.argv[1]===fileURLToPath(import.meta.url)){
 const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..'),logs=resolve(homedir(),'Library/Logs/xiaoai-realtime-voice'),agent=resolve(homedir(),'Library/LaunchAgents/com.LOCAL_USER.xiaoai-realtime-voice.plist');
 if(!existsSync(resolve(homedir(),'Applications/Xiaoai Native Voice.app/Contents/MacOS/node')))throw Error('Install the Xiaoai audio runtime and approve its local network access first');
 if(existsSync(agent))throw Error('Refusing to replace existing launch agent');
 mkdirSync(logs,{recursive:true,mode:0o700});for(const n of ['stdout.log','stderr.log'])writeFileSync(resolve(logs,n),'',{mode:0o600,flag:'a'});
 writeFileSync(agent,launchAgent(root,logs),{mode:0o600,flag:'wx'});execFileSync('plutil',['-lint',agent],{stdio:'ignore'});execFileSync('launchctl',['bootstrap','gui/'+process.getuid(),agent],{stdio:'ignore'});console.log('Realtime service installed; feature remains disabled.');
}
